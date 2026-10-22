"""Генератор `platform_roles_generated.py` из каталога `packages/contracts/platform-rbac.v2.yaml`.

Каталог возможностей (ADR-0012) — единственный источник отображения «раздел × уровень → права
CRM и ERP», системных ролей, шаблонов ролей и правила базовой роли CRM. Модуль в репозитории не
правится руками: `make -C apps/crm platform-roles` пересоздаёт его, тест
`tests/unit/domain/test_platform_roles.py` сверяет файл с каталогом. Контейнер CRM не содержит
`packages/`, поэтому данные каталога живут в коде.

Использование (из backend/): uv run python ../scripts/gen_platform_roles.py [--check]
"""

import argparse
import sys
from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parents[3]
CONTRACT = REPO / "packages" / "contracts" / "platform-rbac.v2.yaml"
DOMAIN = REPO / "apps" / "crm" / "backend" / "app" / "domain"
OUTPUT = DOMAIN / "platform_roles_generated.py"
LEVELS = ("read", "full")

HEADER = '''\
"""Каталог возможностей Платформы (роли как данные). ГЕНЕРИРУЕТСЯ — не править руками (ADR-0012).

Источник: packages/contracts/platform-rbac.v2.yaml (version {version}). Пересоздание:
`make -C apps/crm platform-roles`; тест `tests/unit/domain/test_platform_roles.py` сверяет
файл с каталогом.
"""

from typing import Final

'''


def _fmt(value: Any, depth: int = 0) -> str:
    """Python-литерал в виде, который `ruff format` не меняет: каждый непустой контейнер раскрыт."""
    pad, inner = "    " * depth, "    " * (depth + 1)
    if isinstance(value, dict):
        if not value:
            return "{}"
        rows = [f"{inner}{_fmt(k)}: {_fmt(v, depth + 1)}," for k, v in value.items()]
        return "{\n" + "\n".join(rows) + f"\n{pad}}}"
    if isinstance(value, (list, tuple)):
        if not value:
            return "()"
        if len(value) == 1 and isinstance(value[0], str):
            return f"({_fmt(value[0])},)"  # `ruff format` сворачивает кортеж из одного элемента
        rows = [f"{inner}{_fmt(v, depth + 1)}," for v in value]
        return "(\n" + "\n".join(rows) + f"\n{pad})"
    if isinstance(value, str):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    raise TypeError(f"unsupported literal: {value!r}")


def _const(name: str, annotation: str, value: Any, comment: str = "") -> str:
    head = f"# {comment}\n" if comment else ""
    return f"{head}{name}: Final[{annotation}] = {_fmt(value)}\n"


def _by_level(backend: dict[str, Any], system: str) -> dict[str, tuple[str, ...]]:
    lists = (backend.get(system) or {}) if backend else {}
    return {level: tuple(lists.get(level, ())) for level in LEVELS if level in lists}


def render(spec: dict[str, Any]) -> str:
    """Текст модуля по разобранному каталогу; формат совместим с `ruff format`."""
    resources: list[dict[str, Any]] = spec["resources"]
    roles: dict[str, dict[str, Any]] = {**spec["system_roles"], **spec["templates"]}
    base = spec["crm_base_role"]
    fields = spec["restricted_fields"]
    field_erp = {name: tuple(f["backend"]["erp"]) for name, f in fields.items()}
    blocks = [
        _const(
            "SYSTEM_ROLE_CODES",
            "tuple[str, ...]",
            tuple(spec["system_roles"]),
            "Системные роли: неизменны, не удаляются (код в `platform_roles.code` как есть).",
        ),
        _const(
            "TEMPLATE_ROLE_CODES",
            "tuple[str, ...]",
            tuple(spec["templates"]),
            "Шаблоны: при первом запуске создаются обычными ролями с кодом `tpl:<код>`.",
        ),
        _const(
            "RESOURCE_KEYS",
            "tuple[str, ...]",
            tuple(r["key"] for r in resources),
            "Разделы каталога в порядке файла.",
        ),
        _const(
            "RESOURCE_LEVELS",
            "dict[str, tuple[str, ...]]",
            {r["key"]: tuple(r.get("levels", LEVELS)) for r in resources},
            "Допустимые уровни доступа раздела.",
        ),
        _const(
            "CRM_BACKEND",
            "dict[str, dict[str, tuple[str, ...]]]",
            {r["key"]: _by_level(r.get("backend", {}), "crm") for r in resources},
            "Раздел -> уровень -> права CRM `ресурс:действие` (уровень full включает read).",
        ),
        _const(
            "ERP_BACKEND",
            "dict[str, dict[str, tuple[str, ...]]]",
            {r["key"]: _by_level(r.get("backend", {}), "erp") for r in resources},
            "Раздел -> уровень -> права ERP (`Permission`; уровень full включает read).",
        ),
        _const(
            "FIELD_ERP_BACKEND",
            "dict[str, tuple[str, ...]]",
            field_erp,
            "Поле с ограничением -> права ERP, которые оно открывает.",
        ),
        _const(
            "ROLE_NAMES",
            "dict[str, dict[str, str]]",
            {code: dict(role["name"]) for code, role in roles.items()},
            "Названия системных ролей и шаблонов (ru, uz, en).",
        ),
        _const(
            "ROLE_ACCESS",
            "dict[str, dict[str, str]]",
            {code: dict(role["access"]) for code, role in roles.items()},
            "Матрица системных ролей и шаблонов: раздел -> full|read (скрытые не хранятся).",
        ),
        _const(
            "ROLE_RESTRICTED_FIELDS",
            "dict[str, tuple[str, ...]]",
            {code: tuple(role["restricted_fields"]) for code, role in roles.items()},
            "Поля с ограничением, которые видит системная роль или шаблон.",
        ),
        _const(
            "CRM_BASE_ROLE_BY_CODE",
            "dict[str, str]",
            dict(base["by_code"]),
            "Базовая роль CRM для старого фронта: роль с кодом (порядок — прежние шесть ролей).",
        ),
        _const(
            "CRM_BASE_ROLE_BY_ACCESS",
            "dict[str, tuple[str, ...]]",
            {
                role: tuple(f"{c['resource']}:{c['level']}" for c in conds)
                for role, conds in base["by_access"].items()
            },
            "Базовая роль CRM для роли без кода: достаточно одного условия `раздел:уровень`.",
        ),
    ]
    return HEADER.format(version=spec["version"]) + "\n".join(blocks)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="только сверить")
    args = parser.parse_args()
    text = render(yaml.safe_load(CONTRACT.read_text(encoding="utf-8")))
    if args.check:
        if OUTPUT.read_text(encoding="utf-8") != text:
            sys.stderr.write(f"{OUTPUT} устарел: make -C apps/crm platform-roles\n")
            return 1
        return 0
    OUTPUT.write_text(text, encoding="utf-8")
    sys.stdout.write(f"platform roles → {OUTPUT}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
