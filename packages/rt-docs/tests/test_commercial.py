"""Блоки коммерческих документов (план 2.6): узлы по контракту, подписи на языке документа, суммы и прописью."""

from decimal import Decimal
from typing import Any

from rt_docs import Layout, Letterhead, validate_blocks
from rt_docs.commercial import Line, Totals, items_table, payment_requisites, totals_block
from rt_docs.prepare import document_html, prepare
from tests import samples

LINES = [
    Line("Комплект скрепления КБ-65", Decimal("2"), Decimal("128150.00"), Decimal("256300.00"), "шт"),
    Line("Подкладка КБ-65", Decimal("2.5"), Decimal("1000"), Decimal("2500"), "кг"),
]
TOTALS = Totals(
    subtotal=Decimal("258800.00"),
    vat_amount=Decimal("31056.00"),
    total=Decimal("289856.00"),
    vat_rate=Decimal("12"),
    paid=Decimal("100000.00"),
)


def blocks(lang: str) -> dict[str, list[dict[str, Any]]]:
    return {
        "doc.items_table": items_table(LINES, "UZS", lang),  # type: ignore[arg-type]
        "doc.totals": totals_block(TOTALS, "UZS", lang),  # type: ignore[arg-type]
        "doc.payment_requisites": payment_requisites(
            lang,  # type: ignore[arg-type]
            recipient="ООО «Демо Рейл»",
            inn="305123456",
            bank_lines=["Р/с 20208000900000000001 · МФО 00014"],
            purpose="Оплата по счёту № СЧ-2026/142",
        ),
    }


def test_blocks_follow_the_contract_and_print_in_the_document_language() -> None:
    for lang in ("ru", "uz", "en"):
        validate_blocks(blocks(lang))
    prepared = prepare(
        samples.invoice(),
        letterhead=Letterhead(company_name="ООО «Демо Рейл»"),
        layout=Layout.COMMERCIAL,
        blocks=blocks("ru"),
    )
    html = document_html(prepared, page_numbers=False)
    for expected in (
        "Наименование",
        "Цена, сум",
        "2,5",
        "Итого к оплате",
        "НДС 12%",
        "Остаток к оплате",
        "Двести восемьдесят девять тысяч",
        "Платёжные реквизиты",
        "МФО 00014",
    ):
        assert expected in html, expected
    uz = items_table(LINES, "UZS", "uz")[0]["content"][0]["content"]
    assert uz[1]["content"][0]["content"][0]["text"] == "Nomi"


def test_paid_rows_only_when_something_was_paid() -> None:
    unpaid = totals_block(Totals(Decimal("100"), Decimal("12"), Decimal("112")), "USD", "en")
    rows = unpaid[0]["content"]
    assert len(rows) == 3
    assert "Amount in words" in str(unpaid[1])
