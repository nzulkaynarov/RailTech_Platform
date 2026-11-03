"""Маскирование персональных данных перед вызовом модели (EDS-REG «Заполнить из файла»; решение юриста 2026-11-02:
персональные данные в модель не уходят, маскирует код до вызова).

Правила — те же, что у CRM (`apps/crm/backend/app/security/pii.py`, помощник почты W18A-P2): e-mail, длинные цифровые
последовательности (телефоны, ИНН, ПИНФЛ — 14 цифр, номера карт и счетов), паспорт РУз (`AA1234567`), дата рождения
рядом со словами «дата рождения», «д.р.», «г.р.», «tug'ilgan sana». Почему копия, а не общий пакет: правил пять строк,
домены не делят код, кроме пакетов шины и документов; общий пакет ради одного модуля — лишняя сборка трёх образов.
Совпадение правил держит тест `tests/test_pii.py` на тех же примерах, что `test_pii.py` CRM; правка правил — в обоих
местах одним PR.

Политика защиты данных для ИИ (PD-BIZ, решение владельца 2026-11-03) — одна на ансамбль, владелец CRM (`ai.pii_policy`),
в EDS приходит событием `crm.ai_policy.changed` (`services/docflow_settings.py`): `business` («Деловая», по умолчанию) —
скрываются только паспорт, ПИНФЛ, номера карт (проверка Луна) и даты рождения в контексте; `strict` («Строгая») — всё
перечисленное выше. Реквизиты компании (ИНН, счета, МФО, телефоны, почта) при «Деловой» остаются.

Отличие EDS: числа маскируются **нумерованными метками** `[number_1]`, `[number_2]` — модель возвращает метку там, где
видела номер (например, исходящий номер письма), и код подставляет исходное значение локально (`unmask`): номер в
модель не уходил, но человеку его не надо перепечатывать.
"""

import re
from dataclasses import dataclass, field
from typing import Final, Literal

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
# «Деловая» политика: ПИНФЛ — ровно 14 цифр подряд (не часть 20-значного счёта) или число после слова ПИНФЛ/PINFL/ЖШШИР.
_PINFL: Final = re.compile(r"(?<!\d)(?<!\d[ \-])\d{14}(?![ \-]?\d)")
_PINFL_LABELLED: Final = re.compile(r"(?i)(\b(?:ПИНФЛ|PINFL|ЖШШИР|JSHSHIR)\b[^\d]{0,8})(\d(?:[ \-]?\d){13})(?!\d)")
# Номер карты: 13–19 цифр подряд или группами по 4; принимается, только если проходит проверку Луна.
_CARD: Final = re.compile(r"(?<!\d)(?<!\d[ \-])(?:\d{13,19}|\d{4}(?:[ \-]\d{4}){2,3}(?:[ \-]\d{1,3})?)(?![ \-]?\d)")
_TOKEN: Final = re.compile(r"\[number_(\d+)\]")


def mask_text(text: str) -> str:
    """Строгая маска как у CRM: `[email]`, `[date]`, `[passport]`, `[number]`."""
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


def mask_numbered(text: str, policy: PiiPolicy) -> Masked:
    """Маска для модели по политике; скрытые числа — нумерованными метками `[number_N]` с локальным возвратом.

    «Строгая»: e-mail, дата рождения, паспорт — без возврата; все длинные числа — метками. «Деловая»: паспорт и дата
    рождения — без возврата; ПИНФЛ и номера карт — метками; ИНН, счета, телефоны и почта остаются в тексте.
    """
    numbers: list[str] = []

    def token(value: str) -> str:
        numbers.append(value)
        return f"[number_{len(numbers)}]"

    if policy == "strict":
        text = _BIRTH.sub(r"\1[date]", _EMAIL.sub("[email]", text))
        text = _DIGITS.sub(lambda m: token(m.group(0)), _PASSPORT.sub("[passport]", text))
        return Masked(text=text, numbers=numbers)

    def card(match: re.Match[str]) -> str:
        digits = re.sub(r"\D", "", match.group(0))
        return token(match.group(0)) if 13 <= len(digits) <= 19 and luhn_ok(digits) else match.group(0)

    text = _PASSPORT.sub("[passport]", _BIRTH.sub(r"\1[date]", text))
    text = _PINFL_LABELLED.sub(lambda m: m.group(1) + token(m.group(2)), text)
    text = _PINFL.sub(lambda m: token(m.group(0)), text)
    text = _CARD.sub(card, text)
    return Masked(text=text, numbers=numbers)
