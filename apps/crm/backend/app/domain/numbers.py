"""Проверка чисел в ответе: каждое число должно встречаться в источниках (SPEC §12).

Метрика «выдуманные числа = 0» считается кодом, а не судьёй-моделью.
"""

import re
from collections.abc import Iterable
from typing import Final

_NUMBER: Final = re.compile(r"\d+(?:[.,]\d+)?")


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
    return {_normalize(m) for m in _NUMBER.findall(text.replace(" ", ""))}


def unsupported_numbers(reply: str, sources: Iterable[str]) -> set[str]:
    """Числа ответа, которых нет ни в одном источнике (фрагменты KB, вопрос клиента)."""
    known: set[str] = set()
    for source in sources:
        known |= extract_numbers(source)
    return extract_numbers(reply) - known
