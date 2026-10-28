"""Границы входа (ревью #295, решения архитектора): лимиты тела, вычистка управляющих символов, инъекции HTML.

Сырой HTML не проходит ни одним путём: текст, атрибуты, данные блоков, код блока, ячейки таблиц, значения переменных,
реквизиты и бланк. Класс в HTML — только из фиксированного набора.
"""

from __future__ import annotations

import json
import re
from typing import Any

import pytest

from rt_docs import (
    BodyError,
    DocumentMeta,
    Layout,
    Letterhead,
    clean_text,
    normalize_body,
    to_docx,
    validate_blocks,
    validate_body,
)
from rt_docs.contracts import MAX_BODY_BYTES, MAX_DEPTH, MAX_TABLE_ROWS
from rt_docs.prepare import document_html, prepare
from rt_docs.resolve import resolve
from tests import samples

IMG = '"><img src="file:///etc/passwd"><script>alert(1)</script>'
ALLOWED_CLASSES = {
    "rt-al-left", "rt-al-center", "rt-al-right", "rt-al-justify", "rt-pb", "rt-table", "rt-grid", "rt-plain",
    "rt-totals", "rt-em", "rt-num", "rt-block", "rt-keep", "rt-block-missing", "rt-var", "rt-var-missing",
    "rt-signature", "rt-sign-role", "rt-sign-line", "rt-sign-caption", "rt-stamp", "rt-brand", "rt-logo", "rt-company",
    "rt-req", "rt-docid", "rt-docno", "rt-docno-inline", "rt-rule", "rt-letter-meta", "rt-addressee", "rt-int-head",
    "rt-title", "rt-body", "rt-footer", "rt-executor", "rt-layout-letter", "rt-layout-internal", "rt-layout-commercial",
}  # fmt: skip


def nested_list(levels: int) -> dict[str, Any]:
    node: dict[str, Any] = samples.para("дно")
    for _ in range(levels):
        node = {"type": "bulletList", "content": [{"type": "listItem", "content": [samples.para("пункт"), node]}]}
    return node


def html(body: dict[str, Any], **kwargs: Any) -> str:
    layout = kwargs.pop("layout", Layout.LETTER)
    letterhead = kwargs.pop("letterhead", samples.LETTERHEAD)
    prepared = prepare(body, letterhead=letterhead, layout=layout, **kwargs)
    return document_html(prepared, page_numbers=True)


def assert_no_raw_html(text: str) -> None:
    body = text.split("</style>", 1)[1]
    assert '<img src="file' not in body and "<script" not in body, "сырой HTML прошёл"
    assert "&lt;img src=&quot;file:///etc/passwd&quot;&gt;" in body or "file:///etc/passwd" not in body
    for classes in re.findall(r'class="([^"]*)"', body):
        assert set(classes.split()) <= ALLOWED_CLASSES, classes


# ─── инъекции ────────────────────────────────────────────────────────────────────────────────────


def test_injection_through_text_variables_cells_signature_meta_and_letterhead_is_escaped() -> None:
    body = samples.body(
        [
            samples.para(IMG, samples.var("counterparty.name")),
            {"type": "table", "content": [samples.row(samples.cell(IMG, header=True)), samples.row(samples.cell(IMG))]},
            samples.signature({"role": IMG, "position": {"var": "company.director_position"}, "name": IMG}),
        ]
    )
    out = html(
        body,
        values={"counterparty.name": IMG, "company.director_position": IMG},
        meta=DocumentMeta(title=IMG, number=IMG, addressee=(IMG,), reply_to=IMG, executor=IMG),
        letterhead=Letterhead(company_name=IMG, requisites=(IMG,), footer=(IMG,)),
        layout=Layout.COMMERCIAL,
    )
    assert out.count("&lt;img src=&quot;file:///etc/passwd&quot;&gt;") >= 10
    assert_no_raw_html(out)


def test_block_data_with_internal_node_types_is_rejected() -> None:
    evil = [{"type": "_block", "code": 'doc.x"><img src="file:///etc/passwd">', "content": []}]
    with pytest.raises(BodyError) as error:
        validate_blocks({"doc.items_table": evil})
    assert any(p.startswith("blocks/doc.items_table") for p in error.value.problems)
    with pytest.raises(BodyError):
        html(samples.invoice(), blocks={"doc.items_table": evil})
    with pytest.raises(BodyError):
        to_docx(
            samples.invoice(), letterhead=samples.LETTERHEAD, layout=Layout.COMMERCIAL, blocks={"doc.items_table": evil}
        )


@pytest.mark.parametrize(
    "blocks",
    [
        {'doc.x"><img src=x>': [samples.para("x")]},
        {"doc.items_table": [{"type": "paragraph", "attrs": {"class": "x"}}]},
        {"doc.items_table": "<img src=x>"},
        {"doc.items_table": [{"type": "html", "text": "<img src=x>"}]},
    ],
)
def test_block_codes_and_data_must_follow_the_contract(blocks: dict[str, Any]) -> None:
    with pytest.raises(BodyError):
        validate_blocks(blocks)


def test_block_class_comes_from_a_fixed_set_not_from_the_code() -> None:
    out = html(samples.invoice(), blocks={"doc.items_table": samples.items_table(1), "doc.totals": samples.totals("—")})
    assert "rt-block-items" not in out and "doc.items_table" not in out.split("</style>", 1)[1]
    assert '<div class="rt-block rt-keep">' in out
    assert_no_raw_html(out)


def test_resolver_rejects_node_types_outside_the_contract() -> None:
    body = samples.body([{"type": "_block", "code": "doc.x", "content": []}])
    with pytest.raises(BodyError):
        resolve(body, values={}, blocks={}, catalog=__import__("rt_docs").load_catalog())


# ─── лимиты и нормализация ────────────────────────────────────────────────────────────────────────


def test_depth_limit_is_a_body_error_not_recursion_error() -> None:
    validate_body(samples.body([nested_list((MAX_DEPTH - 3) // 2)]))
    for levels in (MAX_DEPTH, 200, 5000):
        with pytest.raises(BodyError) as error:
            validate_body(samples.body([nested_list(levels)]))
        assert "depth" in str(error.value)


def test_table_row_limit() -> None:
    validate_body(samples.body(samples.items_table(MAX_TABLE_ROWS - 1)))
    with pytest.raises(BodyError) as error:
        validate_body(samples.body(samples.items_table(MAX_TABLE_ROWS)))
    assert "content" in str(error.value)


def test_size_limit() -> None:
    big = samples.body([samples.para("я" * 15000) for _ in range(40)])
    assert len(json.dumps(big, ensure_ascii=False).encode()) > MAX_BODY_BYTES
    with pytest.raises(BodyError) as error:
        validate_body(big)
    assert "1 MB" in str(error.value) or "bytes" in str(error.value)


@pytest.mark.parametrize("bad", [None, [], "строка", 42])
def test_body_must_be_an_object(bad: Any) -> None:
    with pytest.raises(BodyError):
        validate_body(bad)


def test_control_characters_are_rejected_by_the_schema_and_cleaned_on_input() -> None:
    body = samples.body([samples.para("a\x00b\x07c\td\ne\rf\x1b")])
    with pytest.raises(BodyError):
        validate_body(body)
    clean = normalize_body(body)
    validate_body(clean)
    assert clean["doc"]["content"][0]["content"][0]["text"] == "abc\td\ne\nf"
    assert body["doc"]["content"][0]["content"][0]["text"].startswith("a\x00"), "вход не меняется"


def test_render_pipeline_cleans_control_characters_in_body_values_and_meta() -> None:
    body = samples.body([samples.para("тело\x00", samples.var("counterparty.name"))])
    out = html(body, values={"counterparty.name": "знач\x01ение"}, meta=DocumentMeta(title="за\x02головок"))
    assert "\x00" not in out and "\x01" not in out and "\x02" not in out
    assert "значение" in out and "заголовок" in out
    result = to_docx(body, letterhead=samples.LETTERHEAD, layout=Layout.LETTER, values={"counterparty.name": "a\x00b"})
    assert result.data[:2] == b"PK"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("a\x0bb", "a\nb"),  # ручной перенос строки из Word (VT)
        ("a\x0cb", "a\nb"),  # разрыв страницы из Word (FF) — перенос строки
        ("a\rb", "a\nb"),
        ("a\r\nb", "a\nb"),
        ("a\ufffeb\uffffc", "abc"),
        ("a\ufdd0b\ufdefc", "abc"),
        ("a\U0001fffeb\U0010ffffc", "abc"),
        ("a\ud800b", "ab"),  # одиночный суррогат
    ],
)
def test_line_breaks_become_newline_and_noncharacters_are_removed(raw: str, expected: str) -> None:
    assert clean_text(raw) == expected
    body = samples.body([samples.para(raw)])
    assert normalize_body(body)["doc"]["content"][0]["content"][0]["text"] == expected


@pytest.mark.parametrize("bad", ["a\ufffe", "a\uffff", "a\ufdd0", "a\x0b", "a\r", "a\ud800"])
def test_schema_rejects_noncharacters_and_stray_breaks(bad: str) -> None:
    with pytest.raises(BodyError):
        validate_body(samples.body([samples.para(bad)]))


def test_docx_survives_noncharacters_after_normalization() -> None:
    body = samples.body([samples.para("x\ufffey\uffff", samples.var("counterparty.name"))])
    result = to_docx(
        body,
        letterhead=samples.LETTERHEAD,
        layout=Layout.LETTER,
        values={"counterparty.name": "v\ufffe"},
        meta=DocumentMeta(title="t\uffff"),
    )
    assert result.data[:2] == b"PK"
