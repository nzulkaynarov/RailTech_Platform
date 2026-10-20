"""Сторож событий ERP → CRM (FIX-37, FIX-35): тело вебхука валидируется по `packages/contracts/events.schema.json`.

Схема и примеры читаются из контракта на каждом прогоне, копий списка полей здесь нет. Контракта нет на диске — это падение
теста с понятным сообщением, не пропуск (как у сторожей OpenAPI, `core/tests/openapi_contract.py`). Проверки те же:
типы, форматы (`date-time` с часовым поясом), `required`, лишние ключи (`additionalProperties: false` в схеме).
Сама проверка — `integration/services/event_contract.py` (она же работает в рантайме: DEBUG — исключение, прод — лог).

Примеры событий — `packages/contracts/examples/events/<тип>.json`, по одному на каждое из 21 событий: единый источник
фикстур для ERP и CRM (`example_event(type)` отдаёт копию, которую тест может менять).
"""

from __future__ import annotations

import copy
import json
from functools import lru_cache
from pathlib import Path

import pytest
from integration.services.event_contract import envelope_errors

EVENTS_SCHEMA_RELATIVE = Path("packages") / "contracts" / "events.schema.json"
EXAMPLES_RELATIVE = Path("packages") / "contracts" / "examples" / "events"

MOUNT_HINT = (
    "Контракт {what} не найден ни в одном родительском каталоге теста. "
    "Бэкенд-тесты ERP идут в контейнере (apps/erp/scripts/test_backend_local.sh): он обязан монтировать "
    "packages/contracts в /packages/contracts. Сторож событий не пропускается."
)


def _find(relative: Path) -> Path:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / relative
        if candidate.exists():
            return candidate
    pytest.fail(MOUNT_HINT.format(what=str(relative)), pytrace=False)


def find_events_schema_path() -> Path:
    return _find(EVENTS_SCHEMA_RELATIVE)


@lru_cache(maxsize=1)
def load_events_schema() -> dict:
    return json.loads(find_events_schema_path().read_text(encoding="utf-8"))


def event_types() -> list[str]:
    """Все типы событий контракта (`$defs.EventType.enum`) — единственный источник «21 событие»."""
    return list(load_events_schema()["$defs"]["EventType"]["enum"])


def event_errors(envelope: dict) -> list[str]:
    """Нарушения схемы событий в теле вебхука (пустой список — тело валидно)."""
    find_events_schema_path()  # нет контракта — падение с подсказкой, а не «всё валидно»
    errors = envelope_errors(envelope)
    assert errors is not None, "схема событий не найдена рантайм-модулем при найденной сторожем"
    return errors


def examples_dir() -> Path:
    return _find(EXAMPLES_RELATIVE)


@lru_cache(maxsize=None)
def _example_text(event: str) -> str:
    path = examples_dir() / f"{event}.json"
    if not path.is_file():
        pytest.fail(f"нет примера packages/contracts/examples/events/{event}.json для события {event}", pytrace=False)
    return path.read_text(encoding="utf-8")


def example_event(event: str) -> dict:
    """Пример тела события из контракта (копия — менять можно)."""
    return copy.deepcopy(json.loads(_example_text(event)))


def example_files() -> list[str]:
    return sorted(path.stem for path in examples_dir().glob("*.json"))
