"""Одно правило строки (UBL LineExtensionAmount): цена × количество, ROUND_HALF_UP до копейки; сумма документа — Σ строк.

Количество — 3 знака, цена — 2, произведение бывает с 5 знаками. Строки счёта раньше округлял при записи Postgres numeric
(от нуля, как HALF_UP), шапку КП — один раз после суммирования без округления строк: счёт не складывался на копейки. Цены ниже ровно на .xx5,
где half-even и half-up расходятся.
"""

from decimal import Decimal

from core.currency import line_amount
from crm.models import Contract, ContractStatus, InvoiceItem, QuoteItem
from crm.services import create_manual_invoice
from crm.services.billing import generate_invoice_from_contract
from crm.services.quotes import QuoteCalculationService
from crm.tests.test_manual_invoice import scenario  # noqa: F401
from crm.tests.test_quote_sections_optional import _quote, lookups, world  # noqa: F401

D = Decimal
# 10.01 × 0.5 = 5.005 → 5.01 (half-up; half-even дал бы 5.00); три строки: Σ строк 15.03, а Σ без округления 15.015 → 15.02.
PRICE, QTY = D("10.01"), D("0.500")


def _fixed_line(quote, name, price=PRICE, qty=QTY, **kw):
    return QuoteItem.objects.create(
        quote=quote,
        imported_raw_name=name,
        quantity=qty,
        frozen_base_price=price,
        client_price_fixed=price,
        position=kw.pop("position", 0),
        **kw,
    )


def test_line_amount_is_half_up_not_half_even():
    assert line_amount(D("10.01"), D("0.500")) == D("5.01")
    assert line_amount(D("10.03"), D("0.500")) == D("5.02")  # 5.015: half-even дал бы 5.02, half-up — тоже; контроль
    assert line_amount(D("10.05"), D("0.500")) == D("5.03")  # 5.025: half-even дал бы 5.02
    assert line_amount(D("0.01"), D("0.500")) == D("0.01")  # 0.005
    assert line_amount(D("3"), D("2")) == D("6.00")


def test_quote_item_line_total_uses_the_rule(world):  # noqa: F811
    item = _fixed_line(_quote(world), "A")
    assert item.line_total == D("5.01")


def test_quote_subtotal_is_sum_of_rounded_lines(world):  # noqa: F811
    quote = _quote(world)
    for i in range(3):
        _fixed_line(quote, f"L{i}", position=i)
    QuoteCalculationService.recalculate_quote(quote.pk)
    quote.refresh_from_db()
    assert quote.subtotal_excl_vat == D("15.03")
    assert quote.subtotal_excl_vat == sum((i.line_total for i in quote.items.all()), D("0"))


def test_invoice_from_quote_lines_add_up_to_subtotal(world):  # noqa: F811
    quote = _quote(world)
    for i in range(3):
        _fixed_line(quote, f"L{i}", position=i)
    QuoteCalculationService.recalculate_quote(quote.pk)
    quote.refresh_from_db()
    contract = Contract.objects.create(
        deal=quote.deal, quote=quote, number="CT-ROUND-1", notes="", status=ContractStatus.objects.get(code="SIGNED")
    )
    invoice, err = generate_invoice_from_contract(contract.pk, actor=None)
    assert err is None
    lines = list(InvoiceItem.objects.filter(invoice=invoice))
    assert [li.line_total_excl_vat for li in lines] == [D("5.01")] * 3
    assert sum((li.line_total_excl_vat for li in lines), D("0")) == invoice.subtotal_excl_vat == D("15.03")


def test_manual_invoice_lines_unchanged_per_line_half_up(scenario):  # noqa: F811
    invoice, err = create_manual_invoice(
        scenario["solo_deal"].id,
        scenario["seller_user"],
        lines=[{"description": "x", "quantity": "0.5", "unit_price_excl_vat": "10.01"}] * 3,
    )
    assert err is None, err
    lines = list(invoice.items.all())
    assert [li.line_total_excl_vat for li in lines] == [D("5.01")] * 3
    assert invoice.subtotal_excl_vat == D("15.03")
