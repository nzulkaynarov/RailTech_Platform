"""Сетка документа (стандарт документов §4, план ДОК-2): вид, инфоблок, окно адресата, метки сгиба, шапка со 2-й
страницы, подвал из колонок. Включается видом документа; без него — прежняя шапка бланка."""

from __future__ import annotations

from dataclasses import replace

from rt_docs.contracts import load_catalog
from rt_docs.css import page_setup
from rt_docs.html import HtmlOptions, build_html
from rt_docs.model import DocumentMeta, Layout, Letterhead, Orientation, Tuning
from rt_docs.prepare import prepare
from rt_docs.resolve import resolve
from tests import samples


def grid_html(
    meta: DocumentMeta = samples.GRID_META,
    *,
    layout: Layout = Layout.COMMERCIAL,
    letterhead: Letterhead = samples.GRID_LETTERHEAD,
    page_numbers: bool = True,
    orientation: Orientation = Orientation.PORTRAIT,
) -> str:
    body = samples.body([samples.para("Текст")])
    resolved = resolve(body, values={}, blocks={}, catalog=load_catalog())
    return build_html(
        resolved.content,
        lang="ru",
        letterhead=letterhead,
        meta=meta,
        setup=page_setup(layout, orientation, None, Tuning()),
        options=HtmlOptions(page_numbers=page_numbers, highlight_missing=True),
    )


def test_grid_needs_a_document_kind() -> None:
    html = grid_html()
    assert 'class="rt-id"' in html and "Коммерческое предложение" in html
    plain = grid_html(replace(samples.GRID_META, kind_label=None))
    assert 'class="rt-id"' not in plain and "rt-brand" in plain


def test_internal_documents_keep_their_compact_head_without_a_kind() -> None:
    html = grid_html(replace(samples.GRID_META, kind_label=None), layout=Layout.INTERNAL)
    assert 'class="rt-id"' not in html and "rt-int-head" in html


def test_memo_is_the_same_sheet_without_window_and_company_footer() -> None:
    """Служебная записка (стандарт §4): вид и инфоблок как у всех, без окна и подвала из колонок, внизу — строка."""
    meta = replace(samples.GRID_META, kind_label="Служебная записка", verification_code="AB12CD34")
    html = grid_html(meta, layout=Layout.INTERNAL)
    assert 'class="rt-id"' in html and "Служебная записка" in html
    assert 'class="rt-id-window"' not in html and 'class="rt-id-return"' not in html
    assert '<table class="rt-fcols">' not in html and "Руководство" not in html
    assert "Внутренний документ · Код проверки AB12CD34" in html


def test_info_block_window_and_contact() -> None:
    html = grid_html()
    assert '<th scope="row">КП №</th><td><span class="rt-code">QT-2026-104</span></td>' in html
    assert '<div class="rt-id-return">ООО «Тест» · ул. Садыка Азимова, 47/33 · 100000 Ташкент</div>' in html
    assert '<div class="rt-id-addr rt-strong">АО «Пример Логистик»</div>' in html
    assert "rt-id-contact" in html and "Р. Ахмедов" in html


def test_contract_has_no_envelope_window() -> None:
    html = grid_html(replace(samples.GRID_META, window=False))
    assert 'class="rt-id-window"' not in html and 'class="rt-id-return"' not in html


def test_running_head_footer_and_fold_marks() -> None:
    html = grid_html()
    assert 'class="rt-runhead"' in html and 'class="rt-idfoot"' in html
    assert "element(rtrunhead)" in html and "@page :first { @top-center { content: none; } }" in html
    assert '<div class="rt-pn"></div>' in html and "counter(page)" in html
    assert html.count("<td>") >= 5 and "Руководство" in html and "Код НДС 3260 1000 0001" in html
    assert '<div class="rt-fold rt-fold-1"></div><div class="rt-fold rt-hole"></div>' in html
    assert '<div class="rt-fold rt-fold-2"></div>' in html


def test_one_page_has_no_page_numbers_and_landscape_no_fold_marks() -> None:
    assert '<div class="rt-pn"></div>' not in grid_html(page_numbers=False)
    assert 'class="rt-fold rt-fold-1"' not in grid_html(orientation=Orientation.LANDSCAPE)


def test_draft_hides_number_and_date_of_the_info_block() -> None:
    prepared = prepare(
        samples.body([samples.para("Текст")]),
        letterhead=samples.GRID_LETTERHEAD,
        layout=Layout.COMMERCIAL,
        meta=samples.GRID_META,
        draft=True,
    )
    rows = {row.label: row for row in prepared.meta.info}
    assert rows["КП №"].value == "без номера" and rows["КП №"].code is False
    assert rows["Дата"].value == "—"
    assert rows["Менеджер"].value == "Д. Сафаров"


def test_grid_text_is_checked_for_missing_glyphs() -> None:
    prepared = prepare(
        samples.body([samples.para("Текст")]),
        letterhead=samples.GRID_LETTERHEAD,
        layout=Layout.COMMERCIAL,
        meta=replace(samples.GRID_META, kind_label="Счёт ☃"),
    )
    assert any("U+2603" in warning for warning in prepared.warnings)
