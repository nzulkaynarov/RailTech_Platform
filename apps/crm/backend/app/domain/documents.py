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

TYPE_WORDS: Final[dict[DocType, tuple[str, ...]]] = {
    "contract": ("договор", "контракт", "shartnoma", "contract", "agreement"),
    "proposal": ("коммерческое предложение", "кп", "предложени", "taklif", "proposal", "quote"),
    "invoice": ("счёт", "счет", "счета", "hisob-faktura", "hisob", "invoice", "bill"),
    "act": ("акт", "dalolatnoma", "act of acceptance", "certificate of completion"),
    "letter": ("письмо", "xat", "letter"),
}
REQUEST_WORDS: Final = (
    "документ",
    "пришлите",
    "пришли",
    "отправьте",
    "скиньте",
    "копию",
    "файл",
    "pdf",
    "hujjat",
    "yuboring",
    "nusxa",
    "document",
    "send me",
    "copy of",
    "file",
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
    is_request = doc_type is not None or any(w in lowered for w in REQUEST_WORDS)
    return DocQuery(
        doc_type=doc_type,
        date_from=date_from,
        date_to=date_to,
        number=number_match.group(1) if number_match else None,
        is_request=is_request,
    )


def _doc_type(lowered: str) -> DocType | None:
    words = set(_WORD.findall(lowered))
    for doc_type, variants in TYPE_WORDS.items():
        for variant in variants:
            if (" " in variant and variant in lowered) or any(w.startswith(variant) for w in words):
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
