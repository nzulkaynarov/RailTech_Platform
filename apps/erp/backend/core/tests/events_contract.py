"""Сторож событий ERP → CRM (FIX-37): тело вебхука валидируется по `packages/contracts/events.schema.json`.

Схема читается из контракта на каждом прогоне, копий списка полей здесь нет. Контракта нет на диске — это падение
теста с понятным сообщением, не пропуск (как у сторожей OpenAPI, `core/tests/openapi_contract.py`). Проверки те же:
типы, форматы (`date-time` с часовым поясом), `required`, лишние ключи (`additionalProperties: false` в схеме).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import pytest
from core.tests.openapi_contract import format_checker
from jsonschema import Draft202012Validator

EVENTS_SCHEMA_RELATIVE = Path("packages") / "contracts" / "events.schema.json"


def find_events_schema_path() -> Path:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / EVENTS_SCHEMA_RELATIVE
        if candidate.exists():
            return candidate
    pytest.fail(
        "Контракт packages/contracts/events.schema.json не найден ни в одном родительском каталоге теста. "
        "Бэкенд-тесты ERP идут в контейнере (apps/erp/scripts/test_backend_local.sh): он обязан монтировать "
        "packages/contracts в /packages/contracts. Сторож событий не пропускается.",
        pytrace=False,
    )


@lru_cache(maxsize=1)
def load_events_schema() -> dict:
    import json

    return json.loads(find_events_schema_path().read_text(encoding="utf-8"))


def event_errors(envelope: dict) -> list[str]:
    """Нарушения схемы событий в теле вебхука (пустой список — тело валидно)."""
    validator = Draft202012Validator(load_events_schema(), format_checker=format_checker)
    return [
        f"{'/'.join(str(part) for part in error.absolute_path) or '<корень>'}: {error.message}"
        for error in sorted(validator.iter_errors(envelope), key=lambda e: list(map(str, e.absolute_path)))
    ]
