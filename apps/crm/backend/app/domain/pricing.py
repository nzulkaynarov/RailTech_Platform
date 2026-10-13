"""Назвал ли бот цену из базы знаний (SPEC §8.1, ADR-0016). Решает код, а не модель.

Цена «названа», если в ответе есть сумма с валютой и это же число есть во фрагментах
базы (в прайсе числа часто стоят в таблице без валюты). Иначе бот лишь пообещал
расчёт менеджера — и передача обязательна.
"""

import re
from collections.abc import Iterable
from typing import Final

_CURRENCY: Final = (
    r"(?:сум\w*|сўм\w*|so['ʻ’]?m\w*|uzs|usd|у\.?\s?е\.?|долл\w*|\$|руб\w*|₽|€|eur\w*"
    r"|тенге|kzt|dollar\w*)"
)
_NUMBER: Final = r"\d[\d\s .,]*\d|\d"
_AMOUNT: Final = re.compile(
    rf"(?P<before>{_NUMBER})\s*(?:млн|тыс\.?|ming|mln|k)?\s*{_CURRENCY}"
    rf"|{_CURRENCY}\s*(?P<after>{_NUMBER})",
    re.IGNORECASE,
)
_ANY_NUMBER: Final = re.compile(_NUMBER)


def _digits(value: str) -> str:
    return re.sub(r"\D", "", value)


def quoted_amounts(text: str) -> set[str]:
    """Суммы с валютой в тексте, только цифры: «1 200 000 сум» → «1200000»."""
    found = set()
    for match in _AMOUNT.finditer(text):
        value = _digits(match.group("before") or match.group("after") or "")
        if value:
            found.add(value)
    return found


def price_quoted(reply: str, fragments: Iterable[str]) -> bool:
    """В ответе названа сумма, которая есть в базе знаний."""
    amounts = quoted_amounts(reply)
    if not amounts:
        return False
    known = {_digits(n) for fragment in fragments for n in _ANY_NUMBER.findall(fragment)}
    return bool(amounts & known)
