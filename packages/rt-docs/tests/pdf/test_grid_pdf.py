"""Сетка документа в PDF (ДОК-2): окно адресата на первой странице, шапка со 2-й, подвал на каждой странице."""

from __future__ import annotations

import pytest

from rt_docs.model import Layout, RenderResult
from rt_docs.pdf import render_pdf
from tests import samples
from tests.pdf.pdfcheck import fonts, pages


@pytest.fixture(scope="module")
def quote() -> RenderResult:
    body = samples.body([samples.para(sentence) for sentence in samples.SENTENCES * 6])
    return render_pdf(body, letterhead=samples.GRID_LETTERHEAD, layout=Layout.COMMERCIAL, meta=samples.GRID_META)


def test_two_pages_without_warnings(quote: RenderResult) -> None:
    assert quote.stats.pages == 2
    assert quote.warnings == ()


def test_first_page_window_and_info(quote: RenderResult) -> None:
    first = pages(quote.pdf)[0].text
    assert "Коммерческое предложение" in first
    assert "ООО «Тест» · ул. Садыка Азимова, 47/33 · 100000 Ташкент" in first
    assert "Контактное лицо" in first and "Действует до" in first
    assert "Стр. 1 из 2" in first


def test_running_head_from_the_second_page_and_footer_on_each(quote: RenderResult) -> None:
    first, second = (page.text for page in pages(quote.pdf))
    assert first.count("QT-2026-104") == 2, "номер — в инфоблоке и заголовке, без шапки второй страницы"
    assert "КП №" in second and "QT-2026-104" in second and "Стр. 2 из 2" in second
    assert "Коммерческое предложение" not in second
    for text in (first, second):
        assert "Руководство" in text and "Код НДС 3260 1000 0001" in text


def test_only_package_fonts(quote: RenderResult) -> None:
    used = fonts(quote.pdf)
    assert used and all("RT-Doc-Sans" in name or "RT-Doc-Mono" in name for name in used), used
    assert any("RT-Doc-Mono" in name for name in used), "номер в инфоблоке — моноширинным"
