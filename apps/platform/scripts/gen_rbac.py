"""Генератор каталога возможностей Платформы из `packages/contracts/platform-rbac.yaml`.

Версия 2 (ADR-0012): роли — данные CRM, администратор создаёт их сам. Контракт — единственный
источник каталога: разделов с уровнями, пунктов меню, полей с ограничением, видов работы «Моей
очереди», двух системных ролей и шаблонов ролей. Из него получаются два файла, руками они не
правятся:

- `apps/platform/bff/app/rbac_generated.py` — данные для BFF (`app/rbac.py` считает по ним доступ);
- `apps/platform/web/src/app/rbac.generated.ts` — данные и чистые функции для SPA.

Использование (из apps/platform/bff): `uv run python ../scripts/gen_rbac.py [--check]`;
через make: `make -C apps/platform rbac` и `rbac-check`; `--check` не пишет файлы, а сверяет их.
Вывод рассчитан на `ruff format` и `prettier` (printWidth 100): `make check-platform` проверяет оба.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import jsonschema
import yaml

REPO = Path(__file__).resolve().parents[3]
CONTRACT = REPO / "packages" / "contracts" / "platform-rbac.yaml"
SCHEMA = REPO / "packages" / "contracts" / "platform-rbac.schema.json"
PY_OUTPUT = REPO / "apps" / "platform" / "bff" / "app" / "rbac_generated.py"
TS_OUTPUT = REPO / "apps" / "platform" / "web" / "src" / "app" / "rbac.generated.ts"

WIDTH = 100
LANGS = ("ru", "uz", "en")
DEFAULT_LEVELS = ("read", "full")


def load() -> dict[str, Any]:
    spec: dict[str, Any] = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(spec)
    return spec


def _check_references(spec: dict[str, Any]) -> None:
    """Меню, очередь и роли ссылаются только на существующие разделы и уровни каталога."""
    levels = {r["key"]: tuple(r.get("levels", DEFAULT_LEVELS)) for r in spec["resources"]}
    for module, items in spec["menu"].items():
        for item, sections in items.items():
            unknown = [s for s in sections if s not in levels]
            if unknown:
                raise SystemExit(f"menu.{module}.{item}: нет разделов {unknown} в resources")
    for r in spec["resources"]:
        if r["module"] not in spec["menu"]:
            raise SystemExit(f"{r['key']}: модуль {r['module']} без секции menu")
    for kind, need in spec["queue"].items():
        if need["level"] not in levels.get(need["resource"], ()):
            where = f"{need['resource']} с уровнем {need['level']}"
            raise SystemExit(f"queue.{kind}: нет раздела {where}")
    for group in ("system_roles", "templates"):
        for code, role in spec[group].items():
            for key, level in role["access"].items():
                if level not in levels.get(key, ()):
                    raise SystemExit(f"{group}.{code}: нет раздела {key} с уровнем {level}")
            unknown = set(role["restricted_fields"]) - set(spec["restricted_fields"])
            if unknown:
                raise SystemExit(f"{group}.{code}: нет полей {sorted(unknown)}")


def _q(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _ordered_access(spec: dict[str, Any], access: dict[str, str]) -> dict[str, str]:
    """Матрица роли в порядке разделов каталога."""
    return {r["key"]: access[r["key"]] for r in spec["resources"] if r["key"] in access}


def _roles(spec: dict[str, Any], group: str) -> dict[str, dict[str, Any]]:
    fields = list(spec["restricted_fields"])
    return {
        code: {
            "name": {lang: role["name"][lang] for lang in LANGS},
            "access": _ordered_access(spec, role["access"]),
            "restricted_fields": [f for f in fields if f in role["restricted_fields"]],
        }
        for code, role in spec[group].items()
    }


def _backends(resource: dict[str, Any]) -> list[str]:
    backend = resource.get("backend") or {}
    return [name for name in ("crm", "erp") if any((backend.get(name) or {}).values())]


# --- Python ---------------------------------------------------------------------------------------


def _py(value: Any, depth: int = 0) -> str:
    """Литерал, который `ruff format` не меняет.

    Непустые словари и кортежи от двух элементов раскрыты (магическая запятая), кортеж из одной
    строки — в строку.
    """
    pad, inner = "    " * depth, "    " * (depth + 1)
    if isinstance(value, dict):
        if not value:
            return "{}"
        rows = [f"{inner}{_py(k)}: {_py(v, depth + 1)}," for k, v in value.items()]
        return "{\n" + "\n".join(rows) + f"\n{pad}}}"
    if isinstance(value, (list, tuple)):
        if not value:
            return "()"
        if len(value) == 1 and isinstance(value[0], str):
            return f"({_py(value[0])},)"
        rows = [f"{inner}{_py(v, depth + 1)}," for v in value]
        return "(\n" + "\n".join(rows) + f"\n{pad})"
    if isinstance(value, str):
        return _q(value)
    raise TypeError(f"unsupported literal: {value!r}")


def _py_const(name: str, annotation: str, value: Any, comment: str) -> list[str]:
    return [f"# {comment}", f"{name}: Final[{annotation}] = {_py(value)}", ""]


def _py_literal(name: str, values: list[str]) -> str:
    one = f"{name} = Literal[{', '.join(_q(v) for v in values)}]"
    if len(one) <= WIDTH:
        return one
    inner = "".join(f"    {_q(v)},\n" for v in values)
    return f"{name} = Literal[\n{inner}]"


def render_py(spec: dict[str, Any]) -> str:
    modules = list(spec["menu"])
    resources = spec["resources"]
    lines: list[str] = [
        '"""Каталог возможностей Платформы. ГЕНЕРИРУЕТСЯ — не править руками (ADR-0012).',
        "",
        f"Источник: packages/contracts/platform-rbac.yaml (version {spec['version']}).",
        "Пересоздание: `make -C apps/platform rbac`; `tests/test_rbac_generated.py` и",
        "`make check-platform` сверяют файл с контрактом. Логика доступа — `app/rbac.py`.",
        "Роли — данные CRM: здесь только каталог, системные роли и шаблоны.",
        '"""',
        "",
        "from typing import Final, Literal, TypedDict",
        "",
        _py_literal("ModuleCode", modules),
        'Level = Literal["full", "read"]',
        _py_literal("RestrictedField", list(spec["restricted_fields"])),
        "",
        "",
        "class CatalogRole(TypedDict):",
        '    """Роль каталога: название (ru/uz/en), матрица и поля с ограничением."""',
        "",
        "    name: dict[str, str]",
        "    access: dict[str, Level]",
        "    restricted_fields: tuple[RestrictedField, ...]",
        "",
        "",
    ]
    lines += _py_const(
        "MODULES",
        "tuple[ModuleCode, ...]",
        modules,
        "Модули рейла в порядке показа.",
    )
    lines += _py_const(
        "RESOURCE_MODULE",
        "dict[str, ModuleCode]",
        {r["key"]: r["module"] for r in resources},
        "Раздел каталога -> модуль (порядок — как в контракте).",
    )
    lines += _py_const(
        "RESOURCE_LEVELS",
        "dict[str, tuple[Level, ...]]",
        {r["key"]: list(r.get("levels", DEFAULT_LEVELS)) for r in resources},
        "Допустимые уровни раздела (скрыто — раздела нет в матрице роли).",
    )
    lines += _py_const(
        "RESOURCE_BACKENDS",
        "dict[str, tuple[str, ...]]",
        {r["key"]: _backends(r) for r in resources},
        "Бэкенды, права в которых даёт раздел (по `backend` каталога).",
    )
    lines += _py_const(
        "MENU",
        "dict[ModuleCode, dict[str, tuple[str, ...]]]",
        spec["menu"],
        "Меню: модуль -> пункт -> разделы; пункт виден, если виден любой из них.",
    )
    lines += _py_const(
        "RESTRICTED_FIELDS",
        "tuple[RestrictedField, ...]",
        list(spec["restricted_fields"]),
        "Поля с ограничением: роль перечисляет поля, которые она видит.",
    )
    lines += _py_const(
        "QUEUE",
        "dict[str, tuple[str, Level]]",
        {kind: [need["resource"], need["level"]] for kind, need in spec["queue"].items()},
        "Вид работы «Моей очереди» -> (раздел, уровень не ниже).",
    )
    lines += _py_const(
        "SYSTEM_ROLES",
        "dict[str, CatalogRole]",
        _roles(spec, "system_roles"),
        "Системные роли (неизменны): название, матрица, поля с ограничением.",
    )
    lines += _py_const(
        "TEMPLATES",
        "dict[str, CatalogRole]",
        _roles(spec, "templates"),
        "Шаблоны ролей: при первом запуске CRM создаёт по ним обычные роли.",
    )
    return "\n".join(lines).rstrip("\n") + "\n"


# --- TypeScript -----------------------------------------------------------------------------------


def _ts_key(name: str) -> str:
    ident = name.replace("_", "a").isalnum() and not name[0].isdigit()
    return name if ident else _q(name)


def _ts(value: Any, indent: int, prefix_len: int) -> str:
    """Литерал, который prettier не меняет.

    Объекты раскрыты (prettier хранит раскрытие), массивы — в строку, если влезают в `printWidth`
    вместе с ключом, иначе по элементу на строке.
    """
    pad = " " * indent
    if isinstance(value, dict):
        if not value:
            return "{}"
        rows = []
        for k, v in value.items():
            head = f"{pad}  {_ts_key(k)}: "
            rows.append(f"{head}{_ts(v, indent + 2, len(head))},")
        return "{\n" + "\n".join(rows) + f"\n{pad}}}"
    if isinstance(value, (list, tuple)):
        items = [_ts(v, indent + 2, 0) for v in value]
        one = "[" + ", ".join(items) + "]"
        if prefix_len + len(one) + 1 <= WIDTH:
            return one
        return "[\n" + "".join(f"{pad}  {it},\n" for it in items) + f"{pad}]"
    if isinstance(value, str):
        return _q(value)
    raise TypeError(f"unsupported literal: {value!r}")


def _ts_const(name: str, value: Any, tail: str, doc: str) -> list[str]:
    head = f"export const {name} = "
    return [f"/** {doc} */", f"{head}{_ts(value, 0, len(head))}{tail};", ""]


TS_HELPERS = """\
const RANK: Record<AccessLevel, number> = { read: 1, full: 2 };

/** Матрица доступа: раздел каталога -> уровень; скрытые разделы не перечисляются. */
export type Access = Partial<Record<string, AccessLevel>>;

type Merged = Partial<Record<ResourceKey, AccessLevel>>;

/** Объединение матриц ролей: максимум по разделу (full > read), порядок каталога. */
export function mergeAccess(matrices: readonly Access[]): Merged {
  const merged: Merged = {};
  for (const key of RESOURCE_KEYS) {
    for (const access of matrices) {
      const level = access[key];
      const best = merged[key];
      if (level && (best === undefined || RANK[level] > RANK[best])) merged[key] = level;
    }
  }
  return merged;
}

/** Уровень раздела в матрице не ниже `need` (`read` — чтение, `full` — изменение). */
export function allows(access: Access, resource: ResourceKey, need: AccessLevel = "read"): boolean {
  const level = access[resource];
  return level !== undefined && RANK[level] >= RANK[need];
}

/** Пункт меню виден, если виден хотя бы один из его разделов (`any_of`). */
export function menuItemVisible(access: Access, module: ModuleCode, item: string): boolean {
  const sections = (MENU[module] as Record<string, readonly ResourceKey[]>)[item];
  return sections?.some((key) => access[key] !== undefined) ?? false;
}

/** Видимые пункты меню модуля в порядке контракта. */
export function visibleMenuItems(access: Access, module: ModuleCode): string[] {
  return Object.keys(MENU[module]).filter((item) => menuItemVisible(access, module, item));
}

/** Модули рейла по порядку: виден хотя бы один пункт меню (виза без пункта модуль не открывает). */
export function modulesOf(access: Access): ModuleCode[] {
  return MODULES.filter((module) => visibleMenuItems(access, module).length > 0);
}

/** Разделы, права в которых даёт бэкенд (`crm` или `erp`), видимые в матрице. */
export function sectionsWithBackend(access: Access, backend: "crm" | "erp"): ResourceKey[] {
  const gives = (key: ResourceKey) =>
    (RESOURCES[key].backends as readonly string[]).includes(backend);
  return RESOURCE_KEYS.filter((key) => access[key] !== undefined && gives(key));
}
"""


def render_ts(spec: dict[str, Any]) -> str:
    modules = list(spec["menu"])
    resources = {
        r["key"]: {
            "module": r["module"],
            "levels": list(r.get("levels", DEFAULT_LEVELS)),
            "backends": _backends(r),
            "label": {lang: r["label"][lang] for lang in LANGS},
        }
        for r in spec["resources"]
    }
    fields = {
        name: {lang: f["description"][lang] for lang in LANGS}
        for name, f in spec["restricted_fields"].items()
    }
    queue = {kind: dict(need) for kind, need in spec["queue"].items()}
    out: list[str] = [
        "// ГЕНЕРИРУЕТСЯ — не править руками (ADR-0012).",
        f"// Источник: packages/contracts/platform-rbac.yaml (version {spec['version']}).",
        "// Пересоздание: make -C apps/platform rbac (make check-platform сверяет с контрактом).",
        "// Разделы, меню, поля, очередь, системные роли и шаблоны — один источник с BFF.",
        "// Роли — данные CRM (названия и матрицы приходят из API).",
        "",
        'export type AccessLevel = "full" | "read";',
        "type I18n = { ru: string; uz: string; en: string };",
        "",
    ]
    out += _ts_const("MODULES", modules, " as const", "Модули рейла в порядке показа.")
    out += ["export type ModuleCode = (typeof MODULES)[number];", ""]
    out += _ts_const(
        "RESOURCES",
        resources,
        " as const satisfies Record<string, ResourceDef>",
        "Разделы каталога: модуль, допустимые уровни, бэкенды, подпись строки матрицы.",
    )
    out[-3:-3] = [
        "interface ResourceDef {",
        "  module: ModuleCode;",
        "  levels: readonly AccessLevel[];",
        "  backends: readonly string[];",
        "  label: I18n;",
        "}",
        "",
    ]
    out += [
        "export type ResourceKey = keyof typeof RESOURCES;",
        "export const RESOURCE_KEYS = Object.keys(RESOURCES) as ResourceKey[];",
        "",
    ]
    out += _ts_const(
        "MENU",
        spec["menu"],
        " as const satisfies Record<ModuleCode, Record<string, readonly ResourceKey[]>>",
        "Меню: модуль -> пункт -> разделы каталога (виден любой из них).",
    )
    out += _ts_const(
        "RESTRICTED_FIELDS",
        fields,
        " as const satisfies Record<string, I18n>",
        "Поля с ограничением: подпись флажка в редакторе роли.",
    )
    out += ["export type RestrictedField = keyof typeof RESTRICTED_FIELDS;", ""]
    out += _ts_const(
        "QUEUE",
        queue,
        " as const satisfies Record<string, { resource: ResourceKey; level: AccessLevel }>",
        "Вид работы «Моей очереди» -> раздел и уровень не ниже.",
    )
    out += [
        "/** Роль каталога: название, матрица и поля с ограничением. */",
        "export interface CatalogRole {",
        "  name: I18n;",
        "  access: Partial<Record<ResourceKey, AccessLevel>>;",
        "  restricted_fields: readonly RestrictedField[];",
        "}",
        "",
    ]
    out += _ts_const(
        "SYSTEM_ROLES",
        _roles(spec, "system_roles"),
        " satisfies Record<string, CatalogRole>",
        "Системные роли (неизменны, в интерфейсе — только чтение).",
    )
    out += _ts_const(
        "TEMPLATES",
        _roles(spec, "templates"),
        " satisfies Record<string, CatalogRole>",
        "Шаблоны ролей для «Создать роль из шаблона».",
    )
    out.append(TS_HELPERS.rstrip("\n"))
    return "\n".join(out) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="только сверить файлы с контрактом")
    args = parser.parse_args()
    spec = load()
    _check_references(spec)
    targets = {PY_OUTPUT: render_py(spec), TS_OUTPUT: render_ts(spec)}
    if args.check:
        stale = [p for p, text in targets.items() if not p.exists() or p.read_text("utf-8") != text]
        for p in stale:
            sys.stderr.write(f"{p.relative_to(REPO)} устарел: make -C apps/platform rbac\n")
        return 1 if stale else 0
    for path, text in targets.items():
        path.write_text(text, encoding="utf-8")
        sys.stdout.write(f"rbac -> {path.relative_to(REPO)}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
