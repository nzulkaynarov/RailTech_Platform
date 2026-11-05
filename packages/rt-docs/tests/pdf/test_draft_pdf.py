"""Проект в PDF (SIGN-1, ADR-0024 п. 4): знак «ПРОЕКТ» на каждой странице, нет номера и даты, итоговый не изменился."""

from __future__ import annotations

from datetime import date
from io import BytesIO
import pytest
from pypdf import PdfReader

from rt_docs.model import DocumentMeta, Layout, RenderResult
from rt_docs.pdf import render_pdf
from tests import samples
from tests.pdf.pdfcheck import pages

WORDS = "Сто пятьдесят два миллиона триста сорок тысяч сум 00 тийин"
NUMBER = "Д-15/26"
FOOTER = "Проект — не является официальным документом"


def contract(*, draft: bool, lang: str = "ru") -> RenderResult:
    body = samples.contract()
    body["lang"] = lang
    return render_pdf(
        body,
        letterhead=samples.LETTERHEAD,
        layout=Layout.COMMERCIAL,
        meta=DocumentMeta(title="Договор поставки", number=NUMBER, date=date(2026, 10, 1)),
        values=samples.VALUES,
        blocks={"doc.spec_table": samples.items_table(6), "doc.totals": samples.totals(WORDS)},
        draft=draft,
    )


def letter(*, draft: bool) -> RenderResult:
    return render_pdf(
        samples.letter_short(),
        letterhead=samples.LETTERHEAD,
        layout=Layout.LETTER,
        meta=samples.LETTER_META,
        values=samples.VALUES,
        draft=draft,
    )


def mark_count(pdf: bytes, text: str) -> list[int]:
    """Сколько раз знак виден на каждой странице: текст знака повёрнут, читаем его по всем ориентациям."""
    counts = []
    for page in PdfReader(BytesIO(pdf)).pages:
        found = 0
        for angle in (0, 90, 180, 270):
            found += page.extract_text(orientations=(angle,)).count(text)
        counts.append(found)
    return counts


@pytest.fixture(scope="module")
def draft_contract() -> RenderResult:
    return contract(draft=True)


@pytest.fixture(scope="module")
def final_contract() -> RenderResult:
    return contract(draft=False)


def test_draft_mark_on_every_page_without_number(draft_contract: RenderResult) -> None:
    assert draft_contract.stats.pages == 3
    assert all(count >= 1 for count in mark_count(draft_contract.pdf, "ПРОЕКТ")), "знак — на каждой странице"
    for page in pages(draft_contract.pdf):
        assert FOOTER in page.text, "колонтитул проекта — на каждой странице"
        assert NUMBER not in page.text.replace("№ " + NUMBER, "")  # номер самого документа
    first = pages(draft_contract.pdf)[0].text
    assert "без номера" in first
    assert "01.10.2026" not in first and "1 октября 2026" not in first


def test_draft_signature_has_no_stamp(draft_contract: RenderResult) -> None:
    text = "\n".join(page.text for page in pages(draft_contract.pdf))
    assert "М. П." not in text


def test_final_is_without_mark_and_keeps_number(final_contract: RenderResult) -> None:
    assert mark_count(final_contract.pdf, "ПРОЕКТ") == [0, 0, 0]
    text = "\n".join(page.text for page in pages(final_contract.pdf))
    assert FOOTER not in text and "без номера" not in text
    assert NUMBER in pages(final_contract.pdf)[0].text and "М. П." in text


def test_final_pdf_is_not_changed_by_draft_flag_default(final_contract: RenderResult) -> None:
    """Итоговый документ не зависит от нового параметра: тот же результат, что без `draft`, страницы и заполненность."""
    body = samples.contract()
    again = render_pdf(
        body,
        letterhead=samples.LETTERHEAD,
        layout=Layout.COMMERCIAL,
        meta=DocumentMeta(title="Договор поставки", number=NUMBER, date=date(2026, 10, 1)),
        values=samples.VALUES,
        blocks={"doc.spec_table": samples.items_table(6), "doc.totals": samples.totals(WORDS)},
    )
    assert (again.stats, again.passes) == (final_contract.stats, final_contract.passes)
    assert [p.text for p in pages(again.pdf)] == [p.text for p in pages(final_contract.pdf)]


@pytest.mark.parametrize(("lang", "mark"), [("uz", "LOYIHA"), ("en", "DRAFT")])
def test_mark_follows_document_language(lang: str, mark: str) -> None:
    result = contract(draft=True, lang=lang)
    assert all(count >= 1 for count in mark_count(result.pdf, mark))
    assert mark_count(result.pdf, "ПРОЕКТ") == [0] * result.stats.pages


def test_draft_letter_has_no_number_and_mark() -> None:
    result = letter(draft=True)
    [first] = pages(result.pdf)
    assert mark_count(result.pdf, "ПРОЕКТ")[0] >= 1
    assert "ИСХ-015/26" not in first.text and "без номера" in first.text and FOOTER in first.text
    final = pages(letter(draft=False).pdf)[0].text
    assert "ИСХ-015/26" in final and FOOTER not in final


def test_mark_does_not_change_pagination(final_contract: RenderResult, draft_contract: RenderResult) -> None:
    """Знак — fixed-элемент вне потока: число страниц то же, что у итогового."""
    assert draft_contract.stats.pages == final_contract.stats.pages
