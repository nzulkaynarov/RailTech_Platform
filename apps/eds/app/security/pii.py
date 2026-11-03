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
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Final, Literal

PiiPolicy = Literal["business", "strict"]
DEFAULT_POLICY: Final[PiiPolicy] = "business"

_EMAIL: Final = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", re.UNICODE)
# ≥ 7 цифр, допускаются пробелы, дефисы, скобки и ведущий плюс: телефоны, ИНН, карты
# («Строгая»).
_DIGITS: Final = re.compile(r"(?<!\w)\+?\d(?:[\s\-()]*\d){6,}(?!\w)")

# --- Общие правила CRM и EDS: код продублирован (домены не делят пакетов), совпадение держит
# один набор векторов packages/contracts/pii/policy-vectors.json, его читают тесты обеих систем;
# правка правил — в обоих местах одним PR.
# Паспорт РУз: серия из двух букв и 7 цифр. Серия — латиницей или похожей кириллицей
# (А В Е К М Н О Р С Т Х); строчные — только слитно с номером («aa1234567»), заглавные — ещё и
# через пробелы, дефис, «№» («AA № 1234567»).
_NOT_WORD: Final = r"(?<![A-Za-z0-9А-Яа-яЁё])"
_PASSPORT: Final = re.compile(
    rf"{_NOT_WORD}(?:[A-Za-zАВЕКМНОРСТХавекмнорстх]{{2}}"
    rf"|[A-ZАВЕКМНОРСТХ]{{2}}[ \t \-]*(?:№|#)?[ \t \-]*)\d{{7}}(?!\d)"
)
# Дата рождения — только в контексте: метка перед датой («дата рождения», «д.р.», «tug'ilgan
# sana», «туғилган сана») или «г.р.» / «д.р.» после (год без числа — тоже).
_MONTHS: Final = (
    "январ|феврал|март|апрел|ма[йя]|июн|июл|август|сентябр|октябр|ноябр|декабр"
    "|yanvar|fevral|mart|aprel|may|iyun|iyul|avgust|sentabr|oktabr|noyabr|dekabr"
    "|january|february|march|april|june|july|august|september|october|november|december"
)
_DATE: Final = (
    r"(?:\d{1,2}[./\-]\d{1,2}[./\-]\d{2,4}|\d{4}-\d{2}-\d{2}"
    rf"|\d{{1,2}}\s+(?:{_MONTHS})\w*\s+\d{{4}}(?:\s*г(?:ода|\.)?)?)"
)
_BIRTH_LABEL: Final = (
    r"(?:дата\s+рожд(?:ения|\.)?|д\.\s?р\.|г\.\s?р\.|рожд\.|родил(?:ся|ась)"
    r"|birth\s*date|date\s+of\s+birth|dob|born"
    r"|tug['‘’ʻʼ`]?ilgan\s+(?:sana|kun|yil)(?:i|si)?"
    r"|ту[гғ]илган\s+(?:сана|кун|йил)(?:и|си)?)"
)
_BIRTH_BEFORE: Final = re.compile(rf"(?<!\w)({_BIRTH_LABEL}\s*[:\-]?\s*){_DATE}", re.IGNORECASE)
_BIRTH_AFTER: Final = re.compile(rf"(?:{_DATE}|(?<!\d)\d{{4}}(?!\d))(\s*(?:г\.\s?р\.|д\.\s?р\.|г/р))", re.IGNORECASE)
# ПИНФЛ — ровно 14 цифр подряд (не часть более длинной цифровой последовательности, например
# 20-значного расчётного счёта), число после слова ПИНФЛ/PINFL/ЖШШИР с пробелами и дефисами,
# либо запись 1-4-4-4-1.
_PINFL: Final = re.compile(r"(?<!\d)\d{14}(?!\d)")
_PINFL_LABELLED: Final = re.compile(r"(?i)(\b(?:ПИНФЛ|PINFL|ЖШШИР|JSHSHIR)\b[^\d]{0,8})(\d(?:[ \-]?\d){13})(?!\d)")
_PINFL_GROUPED: Final = re.compile(r"(?<!\d)(?<!\d[ \-.])\d[ \-]\d{4}[ \-]\d{4}[ \-]\d{4}[ \-]\d(?!\d)")
# Карта: 13, 15–19 цифр подряд или четыре группы по 4 через пробел, дефис, точку или двойной
# пробел — только с проверкой Луна, независимо от соседних чисел (срок «03/27»). Группа цифр,
# которой предшествует длинный блок цифр, и цепочка из пяти и более групп по 4 (расчётный счёт
# «2020 8000 9001 2345 6001») картой не считаются; пятая группа-год — срок.
_CARD_PLAIN: Final = re.compile(r"(?<!\d)(?:\d{13}|\d{15,19})(?!\d)")
_SEP: Final = r"(?:[ \-.]|  )"
_CHAIN: Final = re.compile(rf"(?<!\d)(?<!\d\d\d[ \-.])(?<!\d\d\d  )\d{{4}}(?!\d)(?:{_SEP}\d{{4}}(?!\d))+")
_TAIL: Final = re.compile(rf"{_SEP}\d{{3}}")
_YEAR: Final = re.compile(r"(?:19|20)\d\d")

Hide = Callable[[str, str], str]


def luhn_ok(digits: str) -> bool:
    """Проверка Луна: номер банковской карты отличается от случайного числа."""
    total = 0
    for index, char in enumerate(reversed(digits)):
        number = int(char)
        if index % 2 == 1:
            number = number * 2 - 9 if number > 4 else number * 2
        total += number
    return total % 10 == 0


def _birth(text: str) -> str:
    return _BIRTH_AFTER.sub(r"[date]\1", _BIRTH_BEFORE.sub(r"\1[date]", text))


def _chains(text: str, hide: Hide) -> str:
    out: list[str] = []
    last = 0
    for match in _CHAIN.finditer(text):
        groups = list(re.finditer(r"\d{4}", match.group(0)))
        if len(groups) == 4 and not _TAIL.match(text, match.end()):
            span = (match.start(), match.end())
        elif len(groups) == 5 and _YEAR.fullmatch(groups[4].group(0)):
            span = (match.start(), match.start() + groups[3].end())
        else:
            continue
        if luhn_ok("".join(g.group(0) for g in groups[:4])):
            out.append(text[last : span[0]] + hide("card", text[span[0] : span[1]]))
            last = span[1]
    return "".join(out) + text[last:]


def _business(text: str, hide: Hide) -> str:
    """«Деловая»: паспорт, ПИНФЛ, номера карт, даты рождения в контексте; остальное остаётся."""
    text = _PASSPORT.sub(lambda m: hide("passport", m.group(0)), _birth(text))
    text = _PINFL_LABELLED.sub(lambda m: m.group(1) + hide("pinfl", m.group(2)), text)
    text = _PINFL_GROUPED.sub(lambda m: hide("pinfl", m.group(0)), text)
    text = _PINFL.sub(lambda m: hide("pinfl", m.group(0)), text)
    text = _CARD_PLAIN.sub(lambda m: hide("card", m.group(0)) if luhn_ok(m.group(0)) else m.group(0), text)
    return _chains(text, hide)


_TOKEN: Final = re.compile(r"\[number_(\d+)\]")


def mask_text(text: str) -> str:
    """Строгая маска как у CRM: `[email]`, `[date]`, `[passport]`, `[number]`."""
    text = _birth(_EMAIL.sub("[email]", text))
    text = _chains(_PASSPORT.sub("[passport]", text), lambda _kind, _value: "[number]")
    return _DIGITS.sub("[number]", text)


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

    Паспорт, ПИНФЛ, номера карт и (при «Строгой») длинные числа возвращаются в поля формы кодом: номер исходящего
    письма, похожий на паспорт («KC1234567»), не теряется. E-mail и даты рождения — без возврата.
    «Деловая»: ИНН, счета, телефоны и почта остаются в тексте.
    """
    numbers: list[str] = []

    def token(_kind: str, value: str) -> str:
        numbers.append(value)
        return f"[number_{len(numbers)}]"

    if policy == "strict":
        text = _birth(_EMAIL.sub("[email]", text))
        text = _PASSPORT.sub(lambda m: token("passport", m.group(0)), text)
        text = _chains(text, token)
        text = _DIGITS.sub(lambda m: token("number", m.group(0)), text)
        return Masked(text=text, numbers=numbers)
    return Masked(text=_business(text, token), numbers=numbers)
