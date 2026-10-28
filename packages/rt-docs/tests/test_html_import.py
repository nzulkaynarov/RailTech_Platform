"""HTML-шаблоны ERP → тело JSON: узлы санитайзера 1:1, плейсхолдеры → переменные и блоки, отчёт о потерях."""

from __future__ import annotations

from rt_docs import html_to_body, load_catalog, validate_body

ERP_INVOICE_TEMPLATE = """
<h2>Счёт на оплату № {{contract.number}}</h2>
<p>Покупатель: <strong>{{counterparty.name}}</strong>, ИНН {{counterparty.inn}}. Дата: {{today}}</p>
<p>{{doc.items_table}}</p>
<div>{{doc.totals}}</div>
<p>Оплата по реквизитам: {{doc.payment_requisites}} в течение 5 дней.</p>
<h4>Условия</h4>
<ul><li>Предоплата <em>100 %</em></li><li>Доставка<ol><li>Самовывоз</li></ol></li></ul>
<table><thead><tr><th>Пункт</th><th colspan="2">Значение</th></tr></thead>
<tbody><tr><td>Срок</td><td>5</td><td>дней</td></tr></tbody></table>
<hr>
<p style="color:red" class="x">Красный <a href="javascript:alert(1)">текст</a> и <a href="https://example.org">сайт</a><br>строка</p>
<img src="data:image/png;base64,AAAA">
<script>alert(1)</script>
<p>{{buyer_name}} {{deal.manager}} {{Bad Code}}</p>
"""


def test_erp_template_converts_to_a_valid_body_with_report() -> None:
    result = html_to_body(ERP_INVOICE_TEMPLATE, catalog=load_catalog())
    validate_body(result.body)
    content = result.body["doc"]["content"]
    types = [n["type"] for n in content]
    assert types[:3] == ["heading", "paragraph", "block"]
    assert content[2]["attrs"] == {"code": "doc.items_table", "locked": True}
    assert content[3]["attrs"]["code"] == "doc.totals"
    # токен блока посреди абзаца делит абзац: текст — блок — текст
    assert [n["type"] for n in content[4:7]] == ["paragraph", "block", "paragraph"]
    paragraph = content[1]["content"]
    assert {"type": "variable", "attrs": {"code": "counterparty.name"}, "marks": [{"type": "bold"}]} in paragraph
    assert {"type": "variable", "attrs": {"code": "system.today"}} in paragraph  # today → system.today
    heading4 = next(n for n in content if n["type"] == "heading" and n["content"][0]["text"] == "Условия")
    assert heading4["attrs"]["level"] == 3
    table = next(n for n in content if n["type"] == "table")
    assert table["content"][0]["content"][1] == {
        "type": "tableHeader",
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Значение"}]}],
        "attrs": {"colspan": 2},
    }
    codes = {loss.code for loss in result.losses}
    assert codes >= {"heading_level", "hr", "image", "attribute", "tag", "placeholder_unknown", "placeholder_invalid"}
    details = " ".join(loss.detail for loss in result.losses)
    assert "{{buyer_name}}" in details and "deal.manager" in details
    assert "<script>" in details and "style" in details and "javascript:" in details


def test_links_breaks_and_lists_survive() -> None:
    result = html_to_body(ERP_INVOICE_TEMPLATE)
    flat = str(result.body)
    assert "'href': 'https://example.org'" in flat and "javascript" not in flat
    assert "'type': 'hardBreak'" in flat
    lists = [n for n in result.body["doc"]["content"] if n["type"] == "bulletList"]
    assert lists and lists[0]["content"][1]["content"][1]["type"] == "orderedList"


def test_plain_text_and_empty_input() -> None:
    plain = html_to_body("Просто   текст\n строкой").body
    assert plain["doc"]["content"] == [
        {"type": "paragraph", "content": [{"type": "text", "text": "Просто текст строкой"}]}
    ]
    empty = html_to_body("").body
    validate_body(empty)
    assert empty["doc"]["content"] == [{"type": "paragraph"}]
