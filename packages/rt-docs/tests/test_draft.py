"""Проект (SIGN-1, ADR-0024 п. 4): знак, «без номера», подпись без печати, колонтитул — на HTML без pango.

Рендер PDF с проверкой знака на каждой странице — `tests/pdf/test_draft_pdf.py`.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from rt_docs.model import DocumentMeta, Lang, Layout
from rt_docs.prepare import document_html, prepare
from tests import samples

MARK = {"ru": "ПРОЕКТ", "uz": "LOYIHA", "en": "DRAFT"}
FOOTER = {
    "ru": "Проект — не является официальным документом",
    "uz": "Loyiha — rasmiy hujjat emas",
    "en": "Draft — not an official document",
}
NO_NUMBER = {"ru": "без номера", "uz": "raqamsiz", "en": "no number"}
META = DocumentMeta(number="ИСХ-015/26", date=date(2026, 10, 28), addressee=("ООО «Пример»",), executor="А. Б. Петрова")


def html(body: dict[str, Any], layout: Layout, *, draft: bool, meta: DocumentMeta = META, **kw: Any) -> str:
    prepared = prepare(body, letterhead=samples.LETTERHEAD, layout=layout, meta=meta, draft=draft, **kw)
    return document_html(prepared, page_numbers=False)


@pytest.mark.parametrize("lang", ["ru", "uz", "en"])
@pytest.mark.parametrize("layout", [Layout.LETTER, Layout.INTERNAL, Layout.COMMERCIAL])
def test_draft_has_mark_footer_and_no_number(layout: Layout, lang: Lang) -> None:
    body = samples.body([samples.para("Текст."), samples.signature({"role": "Директор"})], lang=lang)
    out = html(body, layout, draft=True)
    assert f'<div class="rt-draft-mark">{MARK[lang]}</div>' in out
    assert FOOTER[lang] in out  # колонтитул @top-left каждой страницы
    assert "ИСХ-015/26" not in out and "28.10.2026" not in out and "2026-10-28" not in out
    if layout is not Layout.INTERNAL:  # у служебки нет номера в шапке (бланк без реквизитов документа)
        assert NO_NUMBER[lang] in out
    assert "М. П." not in out and "M. Oʻ." not in out and "Seal" not in out  # печати нет


def test_final_is_unchanged() -> None:
    """Итоговый документ: ни знака, ни колонтитула проекта; номер, дата и «М. П.» на месте."""
    body = samples.body([samples.para("Текст."), samples.signature({"role": "Директор"})])
    for layout in (Layout.LETTER, Layout.COMMERCIAL):
        out = html(body, layout, draft=False)
        assert 'class="rt-draft-mark"' not in out and FOOTER["ru"] not in out and "без номера" not in out
        assert "ИСХ-015/26" in out and "М. П." in out


def test_draft_default_is_off() -> None:
    body = samples.body([samples.para("Текст.")])
    prepared = prepare(body, letterhead=samples.LETTERHEAD, layout=Layout.LETTER, meta=META)
    assert prepared.draft is False


def test_draft_replaces_document_number_and_date_variables() -> None:
    """Номер и дата самого документа, переданные переменными, в проекте не печатаются."""
    body = samples.body([samples.para("№ ", samples.var("document.number"), " от ", samples.var("document.date"))])
    values = {"document.number": "ИСХ-015/26", "document.date": date(2026, 10, 28)}
    final = html(body, Layout.LETTER, draft=False, values=values)
    assert "ИСХ-015/26" in final and "октября 2026" in final
    draft = html(body, Layout.LETTER, draft=True, values=values)
    assert "ИСХ-015/26" not in draft and "октября" not in draft and "без номера" in draft
