"""Проверка тела вебхука по `packages/contracts/events.schema.json` перед постановкой в журнал (FIX-35, I-15).

Единственный источник формы события — файл контракта; копий списка полей в коде нет. Режим (`ERP_EVENTS_CONTRACT_MODE`):

- `strict` — несоответствие поднимает `EventContractError`: событие не создаётся, ошибка видна сразу в DEBUG-стенде и в
  тестах (в тестах режим включён автоматически, conftest);
- `log` — в лог уровня ERROR пишутся тип события, путь и правило схемы БЕЗ значений полей (ПДн), событие уходит как есть (прод: потерять событие хуже, чем отправить
  его с ошибкой формы — CRM запишет его как `rejected`, это видно в центре внешних сервисов);
- `off` — не проверять.

По умолчанию `strict` при DEBUG и `log` в проде. Схема читается так же, как `mcp-tools.json`: `ERP_EVENTS_SCHEMA_PATH`,
`/packages/contracts/events.schema.json` (монтируется в контейнер), затем `packages/contracts` в родителях этого файла
(запуск из клона). Схемы нет — предупреждение в лог один раз (в образ прода контракт не вшит, FIX-36); в тестах отсутствие
схемы — падение сторожа `core/tests/events_contract.py`.
"""

from __future__ import annotations

import datetime
import json
import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Final
from urllib.parse import urlparse

from django.conf import settings
from jsonschema import Draft202012Validator, FormatChecker

logger = logging.getLogger(__name__)

SCHEMA_RELATIVE: Final = Path("packages") / "contracts" / "events.schema.json"
MOUNTED_PATH: Final = Path("/packages/contracts/events.schema.json")
MODES: Final = ("strict", "log", "off")


class EventContractError(ValueError):
    """Событие не соответствует events.schema.json (режим `strict`)."""


format_checker = FormatChecker(formats=())


@format_checker.checks("date", raises=ValueError)
def _is_date(value: Any) -> bool:
    if not isinstance(value, str):
        return True
    datetime.date.fromisoformat(value)
    return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", value))


@format_checker.checks("date-time", raises=ValueError)
def _is_datetime(value: Any) -> bool:
    if not isinstance(value, str):
        return True
    return datetime.datetime.fromisoformat(value).tzinfo is not None  # RFC 3339: часовой пояс обязателен


@format_checker.checks("uri")
def _is_uri(value: Any) -> bool:
    if not isinstance(value, str):
        return True
    parsed = urlparse(value)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def schema_path() -> Path | None:
    configured = (getattr(settings, "ERP_EVENTS_SCHEMA_PATH", "") or "").strip()
    if configured:
        path = Path(configured)
        return path if path.is_file() else None
    if MOUNTED_PATH.is_file():
        return MOUNTED_PATH
    for parent in Path(__file__).resolve().parents:
        candidate = parent / SCHEMA_RELATIVE
        if candidate.is_file():
            return candidate
    return None


@lru_cache(maxsize=4)
def _validator_for(path: str) -> Draft202012Validator:
    schema = json.loads(Path(path).read_text(encoding="utf-8"))
    return Draft202012Validator(schema, format_checker=format_checker)


def contract_mode() -> str:
    configured = (getattr(settings, "ERP_EVENTS_CONTRACT_MODE", "") or "").strip().lower()
    if configured in MODES:
        return configured
    return "strict" if settings.DEBUG else "log"


def _violations(envelope: dict[str, Any]) -> list[tuple[str, str, str]] | None:
    """(путь, правило схемы, сообщение) по каждому нарушению; `None` — схемы на диске нет."""
    path = schema_path()
    if path is None:
        return None
    validator = _validator_for(str(path))
    return [
        (
            "/".join(str(part) for part in error.absolute_path) or "<корень>",
            str(error.validator),
            error.message,
        )
        for error in sorted(validator.iter_errors(envelope), key=lambda e: list(map(str, e.absolute_path)))
    ]


def envelope_errors(envelope: dict[str, Any]) -> list[str] | None:
    """Нарушения схемы с текстом (пустой список — тело валидно); `None` — схемы на диске нет."""
    violations = _violations(envelope)
    if violations is None:
        return None
    return [f"{where}: {message}" for where, _rule, message in violations]


_warned_missing = False


def check_envelope(envelope: dict[str, Any]) -> None:
    """Проверка тела события перед отправкой по режиму `ERP_EVENTS_CONTRACT_MODE` (см. модуль)."""
    global _warned_missing
    mode = contract_mode()
    if mode == "off":
        return
    violations = _violations(envelope)
    if violations is None:
        if not _warned_missing:
            _warned_missing = True
            logger.warning("events.schema.json не найден: события ERP → CRM не проверяются по контракту")
        return
    if not violations:
        return
    event = envelope.get("event")
    if mode == "strict":
        # Исключение видно только в DEBUG и в тестах: там текст нарушения (с значением) нужен для отладки.
        details = "; ".join(f"{where}: {message}" for where, _rule, message in violations)
        raise EventContractError(f"Событие {event!r} не соответствует events.schema.json: {details}")
    # Прод: в журнал — только путь, правило схемы и тип события. Значения полей (имена, замечания клиентов) — ПДн.
    brief = "; ".join(f"{where} ({rule})" for where, rule, _message in violations)
    logger.error("Событие %r не соответствует events.schema.json: %s", event, brief)
