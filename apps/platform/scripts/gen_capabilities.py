"""Генератор каталога «что может человек» (ДОСТ-1) из `packages/contracts/platform-capabilities.yaml`.

Руками не правится: `bff/app/capabilities_generated.py` — данные для `app/capabilities.py` (JSON внутри строки: `ruff
format` строку не трогает). Вместе с каталогом в файл попадают таблицы «раздел → уровень → коды бэкендов» из
`platform-rbac.yaml` (с накоплением: `full` включает `read`), поля с ограничением и полный список кодов ERP — по ним BFF
считает, какие действия включены у сотрудника, ровно так, как права считает CRM.

Использование (из apps/platform/bff): `uv run python ../scripts/gen_capabilities.py [--check]`; через make —
`make -C apps/platform rbac` и `rbac-check`.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import jsonschema
import yaml

REPO = Path(__file__).resolve().parents[3]
CONTRACTS = REPO / "packages" / "contracts"
SOURCE = CONTRACTS / "platform-capabilities.yaml"
SCHEMA = CONTRACTS / "platform-capabilities.schema.json"
RBAC = CONTRACTS / "platform-rbac.yaml"
ERP_API = CONTRACTS / "openapi" / "erp-integration.yaml"
OUTPUT = REPO / "apps" / "platform" / "bff" / "app" / "capabilities_generated.py"

LEVELS = ("view", "work", "decide")
BACKENDS = ("crm", "erp", "eds")
HEADER = '''"""Каталог «что может человек» (ДОСТ-1). ГЕНЕРИРУЕТСЯ — не править руками.

Источник: packages/contracts/platform-capabilities.yaml (version 1) и platform-rbac.yaml.
Пересоздание: `make -C apps/platform rbac`; `make check-platform` сверяет файл с контрактом.
Логика — `app/capabilities.py`.
"""

import json
from typing import Any, Final

DATA: Final[dict[str, Any]] = json.loads(
    """'''


def _tables(rbac: dict[str, Any]) -> dict[str, Any]:
    """Раздел -> бэкенд -> уровень -> коды (накопленные: `full` включает `read`)."""
    result: dict[str, Any] = {}
    for resource in rbac["resources"]:
        per_backend: dict[str, dict[str, list[str]]] = {}
        for backend, levels in (resource.get("backend") or {}).items():
            read = list(levels.get("read", []))
            full = list(dict.fromkeys([*read, *levels.get("full", [])]))
            per_backend[backend] = {"read": read, "full": full}
        result[resource["key"]] = per_backend
    return result


def build() -> dict[str, Any]:
    spec = yaml.safe_load(SOURCE.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(json.loads(SCHEMA.read_text(encoding="utf-8"))).validate(spec)
    rbac = yaml.safe_load(RBAC.read_text(encoding="utf-8"))
    erp_api = yaml.safe_load(ERP_API.read_text(encoding="utf-8"))
    resources = {r["key"]: tuple(r.get("levels", ("read", "full"))) for r in rbac["resources"]}
    fields = set(rbac["restricted_fields"])
    seen: set[str] = set()
    group_keys = {g["key"] for g in spec["groups"]}
    for cap in spec["capabilities"]:
        if cap["key"] in seen:
            raise SystemExit(f"capability {cap['key']}: повтор ключа")
        seen.add(cap["key"])
        if cap["group"] not in group_keys:
            raise SystemExit(f"capability {cap['key']}: нет группы {cap['group']}")
        keys: set[str] = set()
        for level, actions in cap["levels"].items():
            for action in actions:
                if action["key"] in keys:
                    raise SystemExit(f"{cap['key']}.{action['key']}: повтор ключа действия")
                keys.add(action["key"])
                for gate in action["gates"]:
                    for alt in gate.split("|"):
                        resource, _, level_name = alt.partition(":")
                        if level_name not in resources.get(resource, ()):
                            raise SystemExit(f"{cap['key']}.{action['key']}: нет условия {alt}")
                missing = set(action.get("fields", [])) - fields
                if missing:
                    raise SystemExit(f"{cap['key']}.{action['key']}: нет полей {sorted(missing)}")
    # Порядок уровней фиксирован: смотреть → работать → решать.
    capabilities = [
        {
            **{k: v for k, v in cap.items() if k != "levels"},
            "levels": [
                {"level": lv, "actions": cap["levels"][lv]} for lv in LEVELS if lv in cap["levels"]
            ],
        }
        for cap in spec["capabilities"]
    ]
    return {
        "version": spec["version"],
        "free_for_all": spec["free_for_all"],
        "groups": spec["groups"],
        "capabilities": capabilities,
        "section_codes": _tables(rbac),
        "field_erp": {
            name: list(f["backend"].get("erp", [])) for name, f in rbac["restricted_fields"].items()
        },
        "erp_all": list(erp_api["components"]["schemas"]["ErpPermission"]["enum"]),
    }


def render() -> str:
    body = json.dumps(build(), ensure_ascii=False, indent=1, sort_keys=False)
    if '"""' in body or "\\" in body.replace("\\n", ""):
        raise SystemExit("в данных каталога недопустимы тройные кавычки и обратная косая черта")
    return f'{HEADER}{body}\n"""\n)\n'


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    text = render()
    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_text(encoding="utf-8") != text:
            print("capabilities_generated.py устарел — make -C apps/platform rbac и закоммитьте")
            return 1
        return 0
    OUTPUT.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
