"""Маскирование персональных данных перед вызовом модели (EDS-REG «Заполнить из файла»; решение юриста 2026-11-02:
персональные данные в модель не уходят, маскирует код до вызова).

Правила — те же, что у CRM (`apps/crm/backend/app/security/pii.py`, помощник почты W18A-P2): e-mail, длинные цифровые
последовательности (телефоны, ИНН, ПИНФЛ — 14 цифр, номера карт и счетов), паспорт РУз (`AA1234567`), дата рождения
рядом со словами «дата рождения», «д.р.», «г.р.». Почему копия, а не общий пакет: правил пять строк, домены не делят
код, кроме пакетов шины и документов; общий пакет ради одного модуля — лишняя сборка трёх образов. Совпадение правил
держит тест `tests/test_pii.py` на тех же примерах, что `test_pii.py` CRM; правка правил — в обоих местах одним PR.

Отличие EDS: числа маскируются **нумерованными метками** `[number_1]`, `[number_2]` — модель возвращает метку там, где
видела номер (например, исходящий номер письма), и код подставляет исходное значение локально (`unmask`): номер в
модель не уходил, но человеку его не надо перепечатывать.
"""

import re
from dataclasses import dataclass, field
from typing import Final

_EMAIL: Final = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", re.UNICODE)
# ≥ 7 цифр, допускаются пробелы, дефисы, скобки и ведущий плюс: телефоны, ИНН, карты.
_DIGITS: Final = re.compile(r"(?<!\w)\+?\d(?:[\s\-()]*\d){6,}(?!\w)")
# Паспорт РУз: серия из двух латинских букв и 7 цифр (пробел между ними допустим).
_PASSPORT: Final = re.compile(r"(?<![A-Za-z0-9])[A-Z]{2}\s?\d{7}(?!\d)")
_BIRTH: Final = re.compile(
    r"(?i)((?:дата\s+рождения|д\.\s?р\.|г\.\s?р\.|birth\s*date|date\s+of\s+birth)\s*[:\-]?\s*)"
    r"\d{1,2}[./\-]\d{1,2}[./\-]\d{2,4}"
)
_TOKEN: Final = re.compile(r"\[number_(\d+)\]")


def mask_text(text: str) -> str:
    """Маска как у CRM: `[email]`, `[date]`, `[passport]`, `[number]`."""
    text = _BIRTH.sub(r"\1[date]", _EMAIL.sub("[email]", text))
    return _DIGITS.sub("[number]", _PASSPORT.sub("[passport]", text))


@dataclass
class Masked:
    text: str
    numbers: list[str] = field(default_factory=list)  # исходные значения меток `[number_N]` (N с 1)

    def unmask(self, value: str) -> str:
        """Метки `[number_N]` в ответе модели → исходные номера (локально); неизвестная метка остаётся как есть."""

        def back(match: re.Match[str]) -> str:
            index = int(match.group(1)) - 1
            return self.numbers[index] if 0 <= index < len(self.numbers) else match.group(0)

        return _TOKEN.sub(back, value)

    def has_tokens(self, value: str) -> bool:
        return bool(_TOKEN.search(value))


def mask_numbered(text: str) -> Masked:
    """Маска для модели: e-mail, дата рождения, паспорт — без возврата; числа — нумерованными метками."""
    numbers: list[str] = []

    def number(match: re.Match[str]) -> str:
        numbers.append(match.group(0))
        return f"[number_{len(numbers)}]"

    text = _BIRTH.sub(r"\1[date]", _EMAIL.sub("[email]", text))
    text = _DIGITS.sub(number, _PASSPORT.sub("[passport]", text))
    return Masked(text=text, numbers=numbers)
