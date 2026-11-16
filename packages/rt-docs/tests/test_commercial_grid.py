"""Блоки сетки документа (стандарт документов §6, план ДОК-3): позиция стопкой, цена «/ 1 ед.», итоги с выделенной
строкой «К оплате» и суммой прописью, условия парами. Узлы — по контракту тела 1.1.0 (метка `code`, абзац `note`)."""

from __future__ import annotations

from decimal import Decimal

from rt_docs.commercial import Line, Totals, conditions_block, grid_totals_block, stacked_items_table
from rt_docs.contracts import validate_blocks
from tests import samples
from tests.test_html import html_of

RAIL = Line(
    "Рельс Р65",
    Decimal("12.5"),
    Decimal("11760000"),
    Decimal("147000000"),
    unit="т",
    article="RT-00387",
    details=("Длина 25 м",),
    note="Цена от 10 т",
    lead="45 дн.",
)
SERVICE = Line("Доставка", Decimal("1"), Decimal("12000000.50"), Decimal("12000000.50"), unit="рейс")


def test_blocks_follow_the_body_contract() -> None:
    validate_blocks(
        {
            "doc.items_table": stacked_items_table([RAIL, SERVICE], "UZS", "ru"),
            "doc.totals": grid_totals_block(
                Totals(Decimal("100"), Decimal("12"), Decimal("112"), vat_rate=Decimal("12")), "UZS", "ru"
            )
            + conditions_block([("Условия оплаты", "100 % предоплата")]),
        }
    )


def test_stacked_item_cell_and_price_per_unit() -> None:
    table = stacked_items_table([RAIL, SERVICE], "UZS", "ru")[0]
    header, rail, service = table["content"]
    assert [c["content"][0]["content"][0]["text"] for c in header["content"]] == [
        "№",
        "Артикул · Позиция",
        "Срок",
        "Кол-во",
        "Цена, сум",
        "Сумма, сум",
    ]
    item = rail["content"][1]["content"]
    assert item[0] == {
        "type": "paragraph",
        "attrs": {"variant": "note"},
        "content": [{"type": "text", "text": "RT-00387", "marks": [{"type": "code"}]}],
    }
    assert item[1]["content"][0]["text"] == "Рельс Р65"
    assert item[3]["content"][0]["marks"] == [{"type": "italic"}]
    price = rail["content"][4]["content"]
    assert price[0]["content"][0]["text"] == "11\u00a0760\u00a0000" and price[1]["content"][0]["text"] == "/ 1 т"
    assert rail["content"][3]["content"][0]["content"][0]["text"] == "12,5 т"
    assert service["content"][2]["content"][0]["content"][0]["text"] == "—", "нет срока — прочерк"
    amount = service["content"][5]["content"][0]["content"][0]["text"]
    assert amount == "12\u00a0000\u00a0000,50", "тийины — только если есть"


def test_without_lead_times_there_is_no_lead_column() -> None:
    table = stacked_items_table([SERVICE], "UZS", "ru")[0]
    assert len(table["content"][0]["content"]) == 5
    assert table["attrs"]["columnWidths"] == [5, 50, 13, 16, 16]


def test_totals_emphasis_row_and_amount_in_words() -> None:
    table = grid_totals_block(
        Totals(Decimal("456980000"), Decimal("54837600"), Decimal("511817600"), vat_rate=Decimal("12")),
        "UZS",
        "ru",
        total_label="К оплате",
    )[0]
    rows = table["content"]
    assert rows[2]["attrs"] == {"emphasis": True}
    assert rows[2]["content"][0]["content"][0]["content"][0]["text"] == "К оплате, сум"
    assert rows[2]["content"][1]["content"][0]["content"][0]["text"] == "511\u00a0817\u00a0600"
    words = rows[3]["content"][0]
    assert words["attrs"] == {"colspan": 2} and words["content"][0]["attrs"] == {"variant": "note"}


def test_partly_paid_total_is_the_balance() -> None:
    rows = grid_totals_block(
        Totals(Decimal("100"), Decimal("12"), Decimal("112"), paid=Decimal("50"), balance=Decimal("62")), "UZS", "ru"
    )[0]["content"]
    assert rows[3]["content"][1]["content"][0]["content"][0]["text"] == "62"


def test_conditions_skip_empty_values() -> None:
    rows = conditions_block([("Условия оплаты", "50 / 50"), ("Гарантия", " "), ("Базис", "")])[0]["content"]
    assert len(rows) == 1
    assert conditions_block([("Гарантия", "")]) == []


def test_note_paragraph_and_code_mark_render() -> None:
    body = samples.body(
        [
            {
                "type": "paragraph",
                "attrs": {"variant": "note", "textAlign": "right"},
                "content": [{"type": "text", "text": "RT-1", "marks": [{"type": "code"}]}],
            }
        ]
    )
    html = html_of(body)
    assert '<p class="rt-note rt-al-right"><code class="rt-code">RT-1</code></p>' in html
