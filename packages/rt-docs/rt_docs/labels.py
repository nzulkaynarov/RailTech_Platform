"""Подписи оформления документа по языку документа (не интерфейса): номера страниц, реквизиты письма, подписи."""

from __future__ import annotations

from .model import Lang

PAGE_OF: dict[Lang, tuple[str, str, str]] = {
    # (до номера, между номером и числом страниц, после) — «Стр. 2 из 3», «Sahifa 2, jami 3», «Page 2 of 3»
    "ru": ("Стр. ", " из ", ""),
    "uz": ("Sahifa ", ", jami ", ""),
    "en": ("Page ", " of ", ""),
}
STAMP: dict[Lang, str] = {"ru": "М. П.", "uz": "M. Oʻ.", "en": "Seal"}
SIGN: dict[Lang, str] = {"ru": "подпись", "uz": "imzo", "en": "signature"}
EXECUTOR: dict[Lang, str] = {"ru": "Исп.: ", "uz": "Ijrochi: ", "en": "Prepared by: "}
REPLY_TO: dict[Lang, str] = {"ru": "На ", "uz": "Javoban: ", "en": "Re: "}
MISSING_BLOCK: dict[Lang, str] = {
    "ru": "Блок «{label}»: данные подставит система",
    "uz": "«{label}» bloki: maʼlumotlarni tizim qoʻyadi",
    "en": "Block “{label}”: the system will insert the data",
}


def number_line(lang: Lang, number: str | None, date_text: str | None) -> str:
    """Регистрационный номер и дата письма: «№ ИСХ-015/26 от 28.10.2026»."""
    if number and date_text:
        return {
            "ru": f"№ {number} от {date_text}",
            "uz": f"{date_text} № {number}",
            "en": f"No. {number} of {date_text}",
        }[lang]
    if number:
        return {"ru": f"№ {number}", "uz": f"№ {number}", "en": f"No. {number}"}[lang]
    return date_text or ""
