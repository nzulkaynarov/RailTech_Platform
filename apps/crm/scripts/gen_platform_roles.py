"""Генератор `platform_roles_generated.py` из `packages/contracts/platform-rbac.yaml` (CRM-01).

Контракт — единственный источник карты «роль Платформы → базовая роль CRM, роли и права ERP»
(ADR-0011). Модуль в репозитории не правится руками: `make -C apps/crm platform-roles`
пересоздаёт его, тест `tests/unit/domain/test_platform_roles.py` сверяет файл с контрактом.

Использование (из backend/): uv run python ../scripts/gen_platform_roles.py [--check]
"""

import argparse
import sys
from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parents[3]
CONTRACT = REPO / "packages" / "contracts" / "platform-rbac.yaml"
DOMAIN = REPO / "apps" / "crm" / "backend" / "app" / "domain"
OUTPUT = DOMAIN / "platform_roles_generated.py"

HEADER = '''\
"""Роли Платформы и их карта в CRM и ERP. ГЕНЕРИРУЕТСЯ — не править руками (CRM-01).

Источник: packages/contracts/platform-rbac.yaml (version {version}). Пересоздание:
`make -C apps/crm platform-roles`; тест `tests/unit/domain/test_platform_roles.py` сверяет
файл с контрактом.
"""

from typing import Final, Literal

'''


def _tuple(items: list[str]) -> str:
    if not items:
        return "()"
    body = ", ".join(f'"{item}"' for item in items)
    return f"({body},)" if len(items) == 1 else f"({body})"


def _literal(name: str, items: list[str]) -> list[str]:
    body = ", ".join(f'"{item}"' for item in items)
    line = f"{name} = Literal[{body}]"
    if len(line) <= 100:
        return [line]
    return [f"{name} = Literal[", *(f'    "{item}",' for item in items), "]"]


def _mapping(name: str, annotation: str, rows: dict[str, str]) -> list[str]:
    lines = [f"{name}: Final[{annotation}] = {{"]
    lines += [f'    "{code}": {value},' for code, value in rows.items()]
    lines.append("}")
    return lines


def render(spec: dict[str, Any]) -> str:
    """Текст модуля по разобранному контракту; формат совместим с `ruff format`."""
    roles: dict[str, dict[str, Any]] = spec["roles"]
    codes = list(roles)
    lines = _literal("PlatformRoleCode", codes)
    lines.append("")
    codes_line = f"PLATFORM_ROLE_CODES: Final[tuple[str, ...]] = {_tuple(codes)}"
    lines.append(codes_line)
    if len(codes_line) > 100:
        lines[-1:] = [
            "PLATFORM_ROLE_CODES: Final[tuple[str, ...]] = (",
            *(f'    "{code}",' for code in codes),
            ")",
        ]
    lines += ["", "# Базовая роль CRM (admin > manager > viewer при нескольких ролях)."]
    base = {c: f'"{roles[c]["crm_base_role"]}"' for c in codes}
    lines += _mapping("CRM_BASE_ROLE", "dict[str, str]", base)
    lines += ["", "# Системные роли ERP -> `role_codes` провижининга."]
    lines += _mapping(
        "ERP_ROLE_CODES",
        "dict[str, tuple[str, ...]]",
        {c: _tuple(list(roles[c]["erp_role_codes"])) for c in codes},
    )
    lines += ["", "# Права ERP поверх шаблонов ролей -> `permissions` провижининга."]
    lines += _mapping(
        "ERP_EXTRA_PERMISSIONS",
        "dict[str, tuple[str, ...]]",
        {c: _tuple(list(roles[c]["erp_extra_permissions"])) for c in codes},
    )
    return HEADER.format(version=spec["version"]) + "\n".join(lines) + "\n"


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
