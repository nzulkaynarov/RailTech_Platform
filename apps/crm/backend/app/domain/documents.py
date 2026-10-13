"""Разбор запроса клиента о документе (SPEC §7.1 customer, сценарий C5). Решает код.

Из текста извлекаются тип документа, период (месяц/год) и номер; модель в
этом не участвует. «Однозначно найден» — ровно один документ после фильтров
или совпадение номера.
"""

import re
from dataclasses import dataclass
from datetime import date
from typing import Final, Literal

DocType = Literal["contract", "proposal", "letter", "invoice", "act", "other"]

_RU_NOUN: Final = r"(?:а|у|ом|е|ы|ов|ам|ами|ах)?"
_UZ_NOUN: Final = r"(?:i|ni|si|ning|ga|da|dan|lar|lari|larni|larning)?"
# Полные словоформы, а не начало слова: «акт» ≠ «актуальная», «счёт» ≠ «счётчик», «xat» ≠ «xatolik».
_TYPE_FORMS: Final[dict[DocType, tuple[str, ...]]] = {
    "contract": (
        rf"договор{_RU_NOUN}",
        rf"контракт{_RU_NOUN}",
        rf"shartnoma{_UZ_NOUN}",
        r"contracts?",
        r"agreements?",
    ),
    "proposal": (
        r"коммерческ\w*\s+предложени\w*",
        r"кп",
        r"предложени(?:е|я|ю|ем|и|й|ями|ях)",
        rf"taklif{_UZ_NOUN}",
        r"proposals?",
        r"quotes?",
    ),
    "invoice": (
        rf"сч[её]т{_RU_NOUN}",
        rf"hisob-faktura{_UZ_NOUN}",
        rf"hisob{_UZ_NOUN}",
        r"invoices?",
        r"bills?",
    ),
    "act": (
        rf"акт{_RU_NOUN}",
        rf"dalolatnoma{_UZ_NOUN}",
        r"act of acceptance",
        r"certificate of completion",
    ),
    "letter": (
        r"письм(?:о|а|у|ом|е|ами|ах)",
        r"пис[её]м",
        rf"xat{_UZ_NOUN}",
        r"letters?",
    ),
}
TYPE_PATTERNS: Final[dict[DocType, re.Pattern[str]]] = {
    doc_type: re.compile(rf"(?<![\w-])(?:{'|'.join(forms)})(?![\w-])", re.IGNORECASE)
    for doc_type, forms in _TYPE_FORMS.items()
}
_REQUEST: Final = re.compile(
    r"(?<![\w-])(?:документ\w*|пришлите|пришли|отправьте|скиньте|копи[юия]|файл\w*|pdf"
    r"|hujjat\w*|yuboring|nusxa\w*|documents?|send me|copy of|files?)(?![\w-])",
    re.IGNORECASE,
)
_CHANGE: Final = re.compile(
    r"(?<![\w-])(?:сниз\w*|сниж\w*|измен\w*|продл\w*|расторг\w*|пересмотр\w*|скидк\w*"
    r"|услови\w*|o'zgartir\w*|uzaytir\w*|bekor\s+qil\w*|chegirma\w*"
    r"|change\w*|extend\w*|terminat\w*|renegotiat\w*|discount\w*|lower\w*)(?![\w-])",
    re.IGNORECASE,
)
MONTHS: Final[dict[str, int]] = {
    **{
        m: i
        for i, m in enumerate(
            (
                "январ",
                "феврал",
                "март",
                "апрел",
                "ма",
                "июн",
                "июл",
                "август",
                "сентябр",
                "октябр",
                "ноябр",
                "декабр",
            ),
            start=1,
        )
    },
    **{
        m: i
        for i, m in enumerate(
            (
                "yanvar",
                "fevral",
                "mart",
                "aprel",
                "may",
                "iyun",
                "iyul",
                "avgust",
                "sentabr",
                "oktabr",
                "noyabr",
                "dekabr",
            ),
            start=1,
        )
    },
    **{
        m: i
        for i, m in enumerate(
            (
                "january",
                "february",
                "march",
                "april",
                "may",
                "june",
                "july",
                "august",
                "september",
                "october",
                "november",
                "december",
            ),
            start=1,
        )
    },
}
_WORD: Final = re.compile(r"[a-zа-яё'ʻ-]+", re.IGNORECASE)
_YEAR: Final = re.compile(r"\b(20\d{2})\b")
_NUMBER: Final = re.compile(
    r"(?:№|\bno\.|\bномер|\braqam|\bnumber|#)\s*([a-zа-я]*\d[\w/-]*)", re.IGNORECASE
)


@dataclass(frozen=True, slots=True)
class DocQuery:
    doc_type: DocType | None
    date_from: date | None
    date_to: date | None
    number: str | None
    is_request: bool


def parse(text: str, today: date) -> DocQuery:
    lowered = text.lower()
    doc_type = _doc_type(lowered)
    number_match = _NUMBER.search(text)
    # Номер («№ 15/2026») не должен читаться как год периода.
    without_number = _NUMBER.sub(" ", lowered)
    date_from, date_to = _period(without_number, today)
    explicit = _REQUEST.search(lowered) is not None
    # «Снизить цену по договору» — про условия, а не про файл: без явной просьбы прислать
    # это не запрос документа (уходит в сервисный запрос / менеджеру).
    is_request = explicit or (doc_type is not None and _CHANGE.search(lowered) is None)
    return DocQuery(
        doc_type=doc_type,
        date_from=date_from,
        date_to=date_to,
        number=number_match.group(1) if number_match else None,
        is_request=is_request,
    )


def _doc_type(lowered: str) -> DocType | None:
    for doc_type, pattern in TYPE_PATTERNS.items():
        if pattern.search(lowered):
            return doc_type
    return None


def _month(word: str) -> int | None:
    # «май/мая/маю» — короткая основа, проверяем отдельно, чтобы не ловить «магазин».
    if word in ("май", "мая", "мае", "маю", "may"):
        return 5
    for stem, month in MONTHS.items():
        if len(stem) > 2 and word.startswith(stem):
            return month
    return None


def _period(lowered: str, today: date) -> tuple[date | None, date | None]:
    year_match = _YEAR.search(lowered)
    year = int(year_match.group(1)) if year_match else None
    month = next((m for w in _WORD.findall(lowered) if (m := _month(w)) is not None), None)
    if month is None:
        if year is None:
            return None, None
        return date(year, 1, 1), date(year + 1, 1, 1)
    if year is None:
        # Месяц без года — последний такой месяц, не позже текущего.
        year = today.year if month <= today.month else today.year - 1
    start = date(year, month, 1)
    end = date(year + (month == 12), month % 12 + 1, 1)
    return start, end
