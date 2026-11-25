"""КП, спецификация договора, счёт и акт показывают клиенту ОДНИ И ТЕ ЖЕ цены строк (confidentiality, К-1).

Статьи расходов КП (доставка, комиссия 10%, скидка) разнесены по ценам строк. Если договор, счёт или акт печатают
«сырые» цены, клиент кладёт КП рядом с ними и видит наценку по каждой строке и в сумме. Сторож держит это.
"""

from decimal import Decimal

import pytest
from rt_docs import Money, format_money

from crm.models import ChargeType, ContractStatus, InvoiceItem, Quote, QuoteCharge, QuoteItem
from crm.services.documents import client_projection_items
from crm.services.documents.projection import client_billable_lines
from crm.tests.test_act_rt_docs import _render as render_act
from crm.tests.test_contract_rt_docs import _render as render_contract
from crm.tests.test_contract_rt_docs import _rt_docs  # noqa: F401 — autouse: договор на rt_docs
from crm.tests.test_sign_draft_mark import _act, _contract, world  # noqa: F401

RAW = (Decimal("1234.00"), Decimal("2345.00"))  # «сырые» цены строк, до разнесения статей
SECRET_SUPPLIER = "Секретный Поставщик ООО"
SECRET_COST = Decimal("313.37")
FORBIDDEN_KEYS = ("cost", "margin", "purchase", "supplier", "landed", "markup", "base_price", "charge")


def _quote_with_charges(world):  # noqa: F811
    quote = world["quote"]
    quote.items.all().delete()
    QuoteItem.objects.create(quote=quote, imported_raw_name="Колодка", quantity=3, frozen_base_price=RAW[0])
    QuoteItem.objects.create(quote=quote, imported_raw_name="Втулка", quantity=2, frozen_base_price=RAW[1])
    freight = ChargeType.objects.get_or_create(code="FREIGHT", defaults={"name": "Фрахт"})[0]
    commission = ChargeType.objects.get_or_create(code="COMMISSION", defaults={"name": "Комиссия"})[0]
    QuoteCharge.objects.create(
        quote=quote, charge_type=freight, amount=Decimal("500.00"), cost_amount=SECRET_COST, sort_order=1
    )
    QuoteCharge.objects.create(quote=quote, charge_type=commission, rate_percent=Decimal("10"), sort_order=2)
    quote = Quote.objects.get(pk=quote.pk)
    assert quote.charges_total > 0
    world["quote"] = quote  # fresh totals for _contract(world, …)
    return quote


def _money(value) -> str:
    return format_money(Money(Decimal(value), "UZS"), "ru").removesuffix("\xa0сум")  # таблицы печатают число без валюты


def _rows(quote):
    return [r for r in client_projection_items(quote) if r["display_type"] == "ITEM"]


@pytest.mark.django_db
def test_billable_lines_equal_quote_projection_and_sum_to_base(world):  # noqa: F811
    quote = _quote_with_charges(world)
    rows, lines = _rows(quote), client_billable_lines(quote)
    assert [(r["final_price_excl_vat"], r["line_total"]) for r in rows] == [
        (ln.final_price_excl_vat, ln.line_total) for ln in lines
    ]
    assert sum(ln.line_total for ln in lines) == quote.total_excl_vat
    assert all(ln.final_price_excl_vat not in RAW for ln in lines)  # статьи разнесены в цены


@pytest.mark.django_db
def test_invoice_lines_and_totals_match_the_quote(world):  # noqa: F811
    from crm.services.billing import generate_invoice_from_contract

    quote = _quote_with_charges(world)
    ContractStatus.objects.get_or_create(code="SIGNED", defaults={"name": "SIGNED", "sort_order": 90})
    contract = _contract(world, "SIGNED")
    invoice, err = generate_invoice_from_contract(contract.pk, actor=None)
    assert err is None
    got = [(i.unit_price_excl_vat, i.line_total_excl_vat) for i in invoice.items.order_by("id")]
    assert got == [(r["final_price_excl_vat"], r["line_total"]) for r in _rows(quote)]
    assert sum(i.line_total_excl_vat for i in invoice.items.all()) == invoice.subtotal_excl_vat == quote.total_excl_vat
    assert invoice.subtotal_excl_vat + invoice.vat_amount == invoice.total_incl_vat


@pytest.mark.django_db
def test_contract_spec_and_act_print_quote_prices_and_no_charge_traces(world):  # noqa: F811
    from crm.services.billing import generate_invoice_from_contract

    quote = _quote_with_charges(world)
    ContractStatus.objects.get_or_create(code="SIGNED", defaults={"name": "SIGNED", "sort_order": 90})
    contract = _contract(world, "SIGNED")
    contract_text = render_contract(contract)["text"]
    invoice, _ = generate_invoice_from_contract(contract.pk, actor=None)
    from crm.models import Act, ActStatus

    act = Act.objects.create(
        deal=world["deal"],
        contract=contract,
        invoice=invoice,
        number="ACT-K1",
        status=ActStatus.objects.get(code="DRAFT"),
        total_amount=invoice.total_incl_vat,
    )
    act_text = render_act(act)["text"]
    for text in (contract_text, act_text):
        for row in _rows(quote):
            assert _money(row["final_price_excl_vat"]) in text
            assert _money(row["line_total"]) in text
        for raw in RAW:
            assert _money(raw) not in text, "сырая цена строки (до статей расходов) в документе клиента"
        for secret in (SECRET_SUPPLIER, _money(SECRET_COST), "Фрахт", "Комиссия"):
            assert secret not in text


@pytest.mark.django_db
def test_no_client_document_context_has_cost_margin_or_supplier_keys(world):  # noqa: F811
    from crm.services.documents import public_quote_page_context

    quote = _quote_with_charges(world)
    quote.items.update(supplier_name=SECRET_SUPPLIER) if hasattr(QuoteItem, "supplier_name") else None

    def keys(node, path=""):
        if isinstance(node, dict):
            for k, v in node.items():
                yield f"{path}.{k}"
                yield from keys(v, f"{path}.{k}")
        elif isinstance(node, (list, tuple)):
            for v in node:
                yield from keys(v, path)

    context = public_quote_page_context(quote)
    leaked = [
        k
        for k in keys({"items": context["items"], "optional_items": context["optional_items"]})
        if any(bad in k.lower() for bad in FORBIDDEN_KEYS)
    ]
    assert not leaked, leaked
    for line in client_billable_lines(quote):  # what contract/invoice/act templates read: only the all-in price
        assert not any(bad in k.lower() for k in vars(line) for bad in FORBIDDEN_KEYS)
    for item in InvoiceItem._meta.get_fields():
        assert not any(bad in item.name.lower() for bad in ("cost", "margin", "purchase", "supplier", "landed"))
