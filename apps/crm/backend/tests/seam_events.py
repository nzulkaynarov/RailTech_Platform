"""Контракт событий ERP → CRM как источник тестовых данных (FIX-35): схема и примеры.

Один источник с тестами ERP (`apps/erp/backend/core/tests/events_contract.py`): пример на каждое
из 21 событий лежит в `packages/contracts/examples/events/<тип>.json`, схема — в
`packages/contracts/events.schema.json`. Копий в тестах CRM нет.
"""

import copy
import json
from functools import cache
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[4]
SCHEMA_PATH = REPO / "packages" / "contracts" / "events.schema.json"
EXAMPLES_DIR = REPO / "packages" / "contracts" / "examples" / "events"


@cache
def schema() -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    return loaded


def event_types() -> list[str]:
    """Все типы событий контракта (`$defs.EventType.enum`)."""
    return list(schema()["$defs"]["EventType"]["enum"])


def example_files() -> list[str]:
    return sorted(path.stem for path in EXAMPLES_DIR.glob("*.json"))


def example_event(event: str) -> dict[str, Any]:
    """Пример тела события из контракта; копия — менять можно."""
    path = EXAMPLES_DIR / f"{event}.json"
    return copy.deepcopy(json.loads(path.read_text(encoding="utf-8")))


def payload_def_name(event: str) -> str:
    """Имя `$defs`-схемы тела события по `allOf` (например, `InvoiceEvent` для `invoice.paid`)."""
    for rule in schema()["allOf"]:
        condition = rule["if"]["properties"]["event"]
        names = [condition["const"]] if "const" in condition else condition["enum"]
        if event in names:
            return str(rule["then"]["properties"]["payload"]["$ref"].rsplit("/", 1)[-1])
    raise KeyError(event)


def deal_required(event: str) -> bool:
    """Требует ли схема `deal` для этого события."""
    for rule in schema()["allOf"]:
        condition = rule["if"]["properties"]["event"]
        names = [condition["const"]] if "const" in condition else condition["enum"]
        if event in names:
            return "deal" in rule["then"].get("required", [])
    raise KeyError(event)


def required_payload_fields(event: str) -> list[str]:
    return list(schema()["$defs"][payload_def_name(event)].get("required", []))
