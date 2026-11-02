"""Маскирование персональных данных в логах и трейсах (SPEC §11, docs/systems/crm/BUSINESS.md §8).

Скрываются e-mail, длинные цифровые последовательности (телефоны, ИНН, ПИНФЛ — 14 цифр,
номера карт и счетов), паспорт РУз (две латинские буквы и 7 цифр, `AA1234567`) и дата рождения
рядом со словами «дата рождения», «д.р.», «г.р.». Используется как процессор structlog, mask-функция
Langfuse и перед вызовом модели помощником канцелярии (W18A-P2, решение юриста 2026-11-02: в
модель — без персональных данных). Тексты в БД не маскируются — это рабочие данные CRM.
"""

import re
from collections.abc import Mapping, MutableMapping
from typing import Any, Final

_EMAIL: Final = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", re.UNICODE)
# ≥ 7 цифр, допускаются пробелы, дефисы, скобки и ведущий плюс: телефоны, ИНН, карты.
_DIGITS: Final = re.compile(r"(?<!\w)\+?\d(?:[\s\-()]*\d){6,}(?!\w)")
# Паспорт РУз: серия из двух латинских букв и 7 цифр (пробел между ними допустим).
_PASSPORT: Final = re.compile(r"(?<![A-Za-z0-9])[A-Z]{2}\s?\d{7}(?!\d)")
_BIRTH: Final = re.compile(
    r"(?i)((?:дата\s+рождения|д\.\s?р\.|г\.\s?р\.|birth\s*date|date\s+of\s+birth)\s*[:\-]?\s*)"
    r"\d{1,2}[./\-]\d{1,2}[./\-]\d{2,4}"
)

SAFE_LOG_KEYS: Final = frozenset(
    {"event", "level", "logger", "timestamp", "request_id", "lead_id", "trace_id", "exception"}
)


def mask_text(text: str) -> str:
    text = _BIRTH.sub(r"\1[date]", _EMAIL.sub("[email]", text))
    return _DIGITS.sub("[number]", _PASSPORT.sub("[passport]", text))


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
