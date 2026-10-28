"""Тело → HTML: экранирование всего текста, только известные узлы, шапка таблицы, подписи, переменные и блоки."""

from __future__ import annotations

from datetime import date
from typing import Any

from rt_docs.contracts import load_catalog
from rt_docs.css import page_setup
from rt_docs.html import HtmlOptions, build_html
from rt_docs.model import DocumentMeta, Layout, Orientation, Tuning, Value
from rt_docs.resolve import resolve
from tests import samples


def html_of(
    body: dict[str, Any],
    *,
    values: dict[str, Value] | None = None,
    blocks: dict[str, Any] | None = None,
    layout: Layout = Layout.LETTER,
    meta: DocumentMeta | None = None,
    page_numbers: bool = False,
    highlight: bool = True,
) -> str:
    resolved = resolve(body, values=values or {}, blocks=blocks or {}, catalog=load_catalog())
    setup = page_setup(layout, Orientation.PORTRAIT, None, Tuning())
    return build_html(
        resolved.content,
        lang=body["lang"],
        letterhead=samples.LETTERHEAD,
        meta=meta or DocumentMeta(),
        setup=setup,
        options=HtmlOptions(page_numbers=page_numbers, highlight_missing=highlight),
    )


def test_text_and_values_are_escaped() -> None:
    body = samples.body([samples.para("<script>alert(1)</script> & ", samples.var("counterparty.name"))])
    html = html_of(body, values={"counterparty.name": '"><img src=x onerror=alert(1)>'})
    assert "<script>" not in html and "<img src=x" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt; &amp; " in html
    assert "&quot;&gt;&lt;img src=x onerror=alert(1)&gt;" in html


def test_meta_and_letterhead_are_escaped() -> None:
    meta = DocumentMeta(title="<b>Договор</b>", number='1"2', addressee=("<i>x</i>",), executor="<u>y</u>")
    html = html_of(samples.letter_short(), meta=meta)
    assert "<b>Договор" not in html and "&lt;b&gt;Договор&lt;/b&gt;" in html
    assert "<i>x</i>" not in html and "<u>y</u>" not in html


def test_missing_variable_is_highlighted_in_preview_and_blank_in_final() -> None:
    body = samples.body([samples.para("Кому: ", samples.var("counterparty.name"))])
    assert '<span class="rt-var rt-var-missing">[Контрагент — название]</span>' in html_of(body)
    final = html_of(body, highlight=False)
    assert 'class="rt-var rt-var-missing"' not in final and "_______________" in final


def test_value_is_formatted_by_document_language() -> None:
    body = samples.body([samples.para(samples.var("contract.date"))], lang="uz")
    assert "2026-yil 1-oktabr" in html_of(body, values={"contract.date": date(2026, 10, 1)})


def test_table_header_rows_repeat_and_widths_are_percent() -> None:
    html = html_of(samples.body(samples.items_table(2)))
    assert "<thead><tr><th><p>№</p></th>" in html
    assert '<col style="width: 5.000%">' in html and '<col style="width: 49.000%">' in html
    assert 'class="rt-num"' in html
    assert "table.rt-table thead { display: table-header-group; }" in html
    assert "table.rt-table tr { break-inside: avoid; }" in html


def test_signature_keeps_with_previous_and_has_stamp() -> None:
    html = html_of(samples.letter_short(), values=samples.VALUES)
    assert '<table class="rt-signature">' in html
    assert "break-inside: avoid; break-before: avoid;" in html
    assert "М. П." in html and "А. А. Демонстрационный" in html


def test_blocks_data_keep_and_missing_placeholder() -> None:
    body = samples.invoice()
    html = html_of(body, blocks={"doc.items_table": samples.items_table(1), "doc.totals": samples.totals("—")})
    assert 'class="rt-block rt-block-totals rt-keep"' in html
    assert "Блок «Платёжные реквизиты»: данные подставит система" in html


def test_locked_block_without_data_prints_its_content() -> None:
    body = samples.body(
        [
            {
                "type": "block",
                "attrs": {"code": "doc.contract_liability", "locked": True},
                "content": [samples.para("Текст")],
            }
        ]
    )
    assert '<div class="rt-block rt-block-contract-liability"><p>Текст</p></div>' in html_of(body)


def test_page_numbers_only_when_asked() -> None:
    assert 'content: "Стр. " counter(page) " из " counter(pages) "";' in html_of(
        samples.letter_short(), page_numbers=True
    )
    assert "counter(pages)" not in html_of(samples.letter_short(), page_numbers=False)
    uz = html_of(samples.letter_uz(), page_numbers=True)
    assert 'content: "Sahifa " counter(page) ", jami " counter(pages) "";' in uz


def test_layouts_differ_in_header_and_footer() -> None:
    letter = html_of(samples.letter_short(), meta=samples.LETTER_META)
    assert '<table class="rt-letter-meta">' in letter and "Генеральному директору" in letter
    assert '<div class="rt-executor">' in letter
    assert "№ ИСХ-015/26 от 28.10.2026" in letter.replace('<span class="rt-docno-inline">', "").replace("</span>", "")
    commercial = html_of(samples.invoice(), layout=Layout.COMMERCIAL, meta=DocumentMeta(number="СЧ-1"))
    assert '<div class="rt-footer">' in commercial and '<table class="rt-letter-meta">' not in commercial
    assert '<div class="rt-docno">СЧ-1</div>' in commercial
    internal = html_of(samples.letter_short(), layout=Layout.INTERNAL)
    assert '<div class="rt-int-head">' in internal and "rtdocs:logo" not in internal


def test_resources_are_only_rtdocs_urls() -> None:
    html = html_of(samples.invoice(), layout=Layout.COMMERCIAL)
    assert 'src="rtdocs:logo"' in html
    assert 'url("rtdocs:fonts/NotoSans-Regular.ttf")' in html
    assert "http://" not in html and "file:" not in html
