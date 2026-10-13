"""Маскирование персональных данных в логах и трейсах (SPEC §11, BUSINESS.md §8).

Скрываются e-mail и длинные цифровые последовательности (телефоны, ИНН,
номера карт и счетов). Используется как процессор structlog и mask-функция
Langfuse. Тексты в БД не маскируются — это рабочие данные CRM.
"""

import re
from collections.abc import Mapping, MutableMapping
from typing import Any, Final

_EMAIL: Final = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", re.UNICODE)
# ≥ 7 цифр, допускаются пробелы, дефисы, скобки и ведущий плюс: телефоны, ИНН, карты.
_DIGITS: Final = re.compile(r"(?<!\w)\+?\d(?:[\s\-()]*\d){6,}(?!\w)")

SAFE_LOG_KEYS: Final = frozenset(
    {"event", "level", "logger", "timestamp", "request_id", "lead_id", "trace_id", "exception"}
)


def mask_text(text: str) -> str:
    return _DIGITS.sub("[number]", _EMAIL.sub("[email]", text))


def mask_value(value: Any) -> Any:
    if isinstance(value, str):
        return mask_text(value)
    if isinstance(value, Mapping):
        return {k: mask_value(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return type(value)(mask_value(v) for v in value)
    return value


def structlog_processor(
    _logger: Any, _method: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    for key, value in list(event_dict.items()):
        if key not in SAFE_LOG_KEYS:
            event_dict[key] = mask_value(value)
    return event_dict


def langfuse_mask(*, data: Any, **_: Any) -> Any:
    """Сигнатура mask-функции Langfuse SDK: `mask(data=...)`."""
    return mask_value(data)
