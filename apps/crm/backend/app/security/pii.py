"""Маскирование персональных данных: в логах и трейсах (SPEC §11, docs/systems/crm/BUSINESS.md §8)
и перед вызовом модели по политике защиты данных для ИИ (PD-BIZ, решение владельца 2026-11-03).

Логи и трейсы — всегда «строго» (`mask_text`): e-mail, длинные цифровые последовательности
(телефоны, ИНН, ПИНФЛ — 14 цифр, номера карт и счетов), паспорт РУз (две латинские буквы и 7 цифр,
`AA1234567`) и дата рождения рядом со словами «дата рождения», «д.р.», «г.р.», «tug'ilgan sana».
Используется как процессор structlog и mask-функция Langfuse.

Текст для модели (`mask_for_model`) — по политике из настройки `ai.pii_policy` (админ, Платформа):
* `business` («Деловая», по умолчанию): паспорт, ПИНФЛ, номера банковских карт (проверка Луна) и
  даты рождения в контексте. Реквизиты компании публичны и в письмах обычны, поэтому ИНН, расчётные
  счета, МФО, телефоны, e-mail, ФИО и адреса остаются;
* `strict` («Строгая»): всё, что скрывает `mask_text` (решение юриста 2026-11-02).

Тексты в БД не маскируются — это рабочие данные CRM.
"""

import re
from collections.abc import Mapping, MutableMapping
from typing import Any, Final, Literal

PiiPolicy = Literal["business", "strict"]
DEFAULT_POLICY: Final[PiiPolicy] = "business"

_EMAIL: Final = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", re.UNICODE)
# ≥ 7 цифр, допускаются пробелы, дефисы, скобки и ведущий плюс: телефоны, ИНН, карты.
_DIGITS: Final = re.compile(r"(?<!\w)\+?\d(?:[\s\-()]*\d){6,}(?!\w)")
# Паспорт РУз: серия из двух латинских букв и 7 цифр (пробел между ними допустим).
_PASSPORT: Final = re.compile(r"(?<![A-Za-z0-9])[A-Z]{2}\s?\d{7}(?!\d)")
_BIRTH: Final = re.compile(
    r"(?i)((?:дата\s+рождения|д\.\s?р\.|г\.\s?р\.|birth\s*date|date\s+of\s+birth"
    r"|tug['\u2018\u2019\u02bb\u02bc`]?ilgan\s+(?:sana|kun)(?:i|si)?)\s*[:\-]?\s*)"
    r"\d{1,2}[./\-]\d{1,2}[./\-]\d{2,4}"
)
# «Деловая» политика. ПИНФЛ — ровно 14 цифр подряд (без соседних цифр, в том числе через пробел или
# дефис, чтобы не резать 20-значный расчётный счёт) либо число после слова ПИНФЛ/PINFL/ЖШШИР.
_PINFL: Final = re.compile(r"(?<!\d)(?<!\d[ \-])\d{14}(?![ \-]?\d)")
_PINFL_LABELLED: Final = re.compile(
    r"(?i)(\b(?:ПИНФЛ|PINFL|ЖШШИР|JSHSHIR)\b[^\d]{0,8})\d(?:[ \-]?\d){13}(?!\d)"
)
# Номер карты: 13–19 цифр подряд или группами по 4; принимается, только если проходит проверку Луна.
_CARD: Final = re.compile(
    r"(?<!\d)(?<!\d[ \-])(?:\d{13,19}|\d{4}(?:[ \-]\d{4}){2,3}(?:[ \-]\d{1,3})?)(?![ \-]?\d)"
)

SAFE_LOG_KEYS: Final = frozenset(
    {"event", "level", "logger", "timestamp", "request_id", "lead_id", "trace_id", "exception"}
)


def mask_text(text: str) -> str:
    """Строгая маска: логи, трейсы и политика «Строгая»."""
    text = _BIRTH.sub(r"\1[date]", _EMAIL.sub("[email]", text))
    return _DIGITS.sub("[number]", _PASSPORT.sub("[passport]", text))


def luhn_ok(digits: str) -> bool:
    """Проверка Луна: номер банковской карты отличается от случайного числа."""
    total = 0
    for index, char in enumerate(reversed(digits)):
        number = int(char)
        if index % 2 == 1:
            number = number * 2 - 9 if number > 4 else number * 2
        total += number
    return total % 10 == 0


def _card(match: re.Match[str]) -> str:
    digits = re.sub(r"\D", "", match.group(0))
    return "[card]" if 13 <= len(digits) <= 19 and luhn_ok(digits) else match.group(0)


def mask_business(text: str) -> str:
    """«Деловая» маска: паспорт, ПИНФЛ, карты, даты рождения в контексте; остальное — как есть."""
    text = _BIRTH.sub(r"\1[date]", text)
    text = _PASSPORT.sub("[passport]", text)
    text = _PINFL_LABELLED.sub(r"\1[pinfl]", text)
    text = _PINFL.sub("[pinfl]", text)
    return _CARD.sub(_card, text)


def mask_for_model(text: str, policy: PiiPolicy = DEFAULT_POLICY) -> str:
    """Текст, который можно отдать модели, по политике защиты данных для ИИ."""
    return mask_text(text) if policy == "strict" else mask_business(text)


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
