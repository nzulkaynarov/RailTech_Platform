"""Проверка чисел в ответе: каждое число должно встречаться в источниках (SPEC §12).

Метрика «выдуманные числа = 0» считается кодом, а не судьёй-моделью. Та же проверка стоит в рантайме
сервисного режима бота (M3-CRM-07): ответ с числом, которого нет в данных ERP, клиенту не уходит.
"""

import re
from collections.abc import Iterable
from typing import Final

_NUMBER: Final = re.compile(r"\d+(?:[.,]\d+)?")
_ISO_DATE: Final = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
# Модель пишет «1 250 000» с неразрывным или узким пробелом; это одно число.
_SPACES: Final = str.maketrans("", "", "   ")


def _normalize(raw: str) -> str:
    value = raw.replace(",", ".")
    if "." in value:
        whole, frac = value.split(".", 1)
        frac = frac.rstrip("0")
        whole = whole.lstrip("0") or "0"
        return f"{whole}.{frac}" if frac else whole
    return value.lstrip("0") or "0"


def extract_numbers(text: str) -> set[str]:
    """Числа текста в нормальной форме: `09:00` → {"9", "0"}, `3,50` → {"3.5"}."""
    return {_normalize(m) for m in _NUMBER.findall(text.translate(_SPACES))}


def date_forms(text: str) -> str:
    """Даты `YYYY-MM-DD` источника в тех видах, в которых их пишут: `25.10.2026`, `25.10`."""
    return "; ".join(f"{d}.{m}.{y}; {d}.{m}" for y, m, d in _ISO_DATE.findall(text))


def unsupported_numbers(reply: str, sources: Iterable[str]) -> set[str]:
    """Числа ответа, которых нет ни в одном источнике (фрагменты KB, вопрос клиента, данные ERP)."""
    known: set[str] = set()
    for source in sources:
        known |= extract_numbers(f"{source} {date_forms(source)}")
    return extract_numbers(reply) - known
