"""G2 — manual invoice «from scratch» (no signed contract).

create_manual_invoice raises a DRAFT invoice on a deal WITHOUT a contract (Odoo / МойСклад
«invoice without contract»; contract=None). Lines import from an active КП (same billable
projection as the contract path) and/or a manual list. Money follows the PRESENTATION currency
(quote_currency), never a line's frozen COST currency (the B1 bug). The DRAFT is hidden from the
buyer and from an outsider, visible to own-company staff; then the existing issue/cancel
lifecycle takes over and payment still rejects a DRAFT.

Self-contained fixtures (tests run --nomigrations, so every lookup code is seeded here).
"""

from datetime import date
from decimal import Decimal

import pytest

from accounts.models import Company, CompanyMember, CompanyType, CustomUser, WorkspaceRole
from accounts.testing import make_cashier
from crm.models import Deal, DealStage, Invoice, InvoiceStatus, Quote, QuoteItem, QuoteStatus
from crm.services import create_manual_invoice
from crm.services.billing import record_payment
from crm.services.invoice_lifecycle import cancel_invoice, issue_invoice
from crm.views.billing import _seller_side_q
from master_data.models import Currency


@pytest.fixture
def scenario(db):
    DealStage.objects.get_or_create(code="DRAFT", defaults={"name": "DRAFT", "sort_order": 10})
    QuoteStatus.objects.get_or_create(code="SENT", defaults={"name": "SENT", "sort_order": 20})
    CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Client", "sort_order": 10})
    CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 20})
    WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})
    for code in ("DRAFT", "ISSUED", "PARTIAL", "PAID", "CANCELLED"):
        InvoiceStatus.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    uzs = Currency.objects.get_or_create(code="UZS", defaults={"name": "Sum", "symbol": "сум", "sort_order": 1})[0]
    usd = Currency.objects.get_or_create(code="USD", defaults={"name": "Dollar", "symbol": "$", "sort_order": 2})[0]

    def _seller(name, inn):
        # O3: продавец с платёжными реквизитами — иначе `issue_invoice` не выпустит счёт (он неоплатен).
        co = Company.objects.create(name=name, inn=inn, bank_account="20208000900001234567", mfo="00443")
        co.types.add(CompanyType.objects.get(code="SUPPLIER"))
        user = CustomUser.objects.create_user(email=f"{inn}@s.test", username=f"{inn}@s.test", password="pw")
        CompanyMember.objects.create(
            user=user, company=co, role=WorkspaceRole.objects.get(code="OWNER"), is_active=True, can_sell=True
        )
        return co, user

    seller, seller_user = _seller("Seller A", "3000000001")
    # Посторонний — участник другой (клиентской) компании: не сотрудник, документов бэк-офиса не видит.
    outsider_co = Company.objects.create(name="Outsider LLC", inn="3000000002")
    outsider_co.types.add(CompanyType.objects.get(code="CLIENT"))
    outsider_user = CustomUser.objects.create_user(email="out@o.test", username="out@o.test", password="pw")
    CompanyMember.objects.create(
        user=outsider_user, company=outsider_co, role=WorkspaceRole.objects.get(code="OWNER"), is_active=True
    )

    # O3: продавец с платёжными реквизитами — иначе `issue_invoice` не выпустит счёт (он неоплатен).
    buyer = Company.objects.create(name="Buyer LLC", inn="6600000001", bank_account="20208000900001234567", mfo="00443")
    buyer.types.add(CompanyType.objects.get(code="CLIENT"))
    buyer_user = CustomUser.objects.create_user(email="buyer@b.test", username="buyer@b.test", password="pw")
    CompanyMember.objects.create(
        user=buyer_user, company=buyer, role=WorkspaceRole.objects.get(code="OWNER"), is_active=True
    )

    deal = Deal.objects.create(title="Deal", company=buyer, stage=DealStage.objects.get(code="DRAFT"))

    # КП owned by A, PRESENTATION currency UZS, a line whose COST currency is USD (the B1 trap).
    quote = Quote.objects.create(
        deal=deal,
        version=1,
        status=QuoteStatus.objects.get(code="SENT"),
        prepared_by=seller_user,
        seller_company=seller,
        quote_currency=uzs,
        vat_rate=Decimal("12.00"),
        subtotal_excl_vat=Decimal("1000000.00"),
        vat_amount=Decimal("120000.00"),
        total_incl_vat=Decimal("1120000.00"),
    )
    QuoteItem.objects.create(
        quote=quote,
        display_type="ITEM",
        frozen_base_price=Decimal("500000.00"),
        frozen_currency=usd,
        quantity=2,
        imported_raw_name="rail-part",
    )
    quote.refresh_from_db()

    # A second deal without a КП — the pure-manual счёт path.
    solo_deal = Deal.objects.create(title="Solo deal", company=buyer, stage=DealStage.objects.get(code="DRAFT"))

    return {
        "deal": deal,
        "solo_deal": solo_deal,
        "quote": quote,
        "seller": seller,
        "seller_user": seller_user,
        "outsider_user": outsider_user,
        "buyer_user": buyer_user,
        "uzs": uzs,
        "usd": usd,
    }


@pytest.mark.django_db
def test_manual_invoice_created_draft_no_contract(scenario):
    invoice, err = create_manual_invoice(
        scenario["deal"].id, scenario["seller_user"], source_quote_id=scenario["quote"].id
    )
    assert err is None
    assert invoice.contract_id is None
    assert invoice.status_code == "DRAFT"
    assert invoice.deal_id == scenario["deal"].id
    assert invoice.number


@pytest.mark.django_db
def test_manual_invoice_currency_is_presentation_not_cost(scenario):
    invoice, err = create_manual_invoice(
        scenario["deal"].id, scenario["seller_user"], source_quote_id=scenario["quote"].id
    )
    assert err is None
    # Presentation currency (UZS) — NOT the line's frozen COST currency (USD). This is the B1 guard.
    assert invoice.currency_id == scenario["uzs"].id
    assert invoice.currency_id != scenario["usd"].id
    quote_item = scenario["quote"].items.first()
    assert invoice.currency_id != quote_item.frozen_currency_id


@pytest.mark.django_db
def test_manual_invoice_lines_match_billable_projection(scenario):
    invoice, err = create_manual_invoice(
        scenario["deal"].id, scenario["seller_user"], source_quote_id=scenario["quote"].id
    )
    assert err is None
    billable = list(scenario["quote"].items.billable())
    assert invoice.items.count() == len(billable) == 1
    line = invoice.items.first()
    quote_item = billable[0]
    assert line.source_quote_item_id == quote_item.id
    assert line.quantity == quote_item.quantity
    assert line.unit_price_excl_vat == quote_item.final_price_excl_vat
    # Header totals mirror the КП header (presentation currency).
    assert invoice.subtotal_excl_vat == scenario["quote"].subtotal_excl_vat
    assert invoice.total_incl_vat == scenario["quote"].total_incl_vat


@pytest.mark.django_db
def test_manual_invoice_with_manual_lines_only(scenario):
    # Pure-manual счёт (no source КП) — allowed on any deal: the seller is always the own company.
    invoice, err = create_manual_invoice(
        scenario["solo_deal"].id,
        scenario["seller_user"],
        lines=[{"description": "Доставка", "quantity": 1, "unit_price_excl_vat": "150000.00"}],
    )
    assert err is None
    assert invoice.contract_id is None
    assert invoice.items.count() == 1
    assert invoice.subtotal_excl_vat == Decimal("150000.00")
    # No source КП → currency left NULL (PDF falls back to UZS), never a cost currency.
    assert invoice.currency_id is None


@pytest.mark.django_db
def test_invoice_supplier_resolves_via_source_quote_when_no_contract(scenario):
    # D0: a manual invoice built from a КП has no contract, but the header supplier must still
    # resolve (via the item's source_quote_item → КП → seller), NOT print «—».
    from crm.services.billing import _invoice_seller_company

    invoice, err = create_manual_invoice(
        scenario["deal"].id, scenario["seller_user"], source_quote_id=scenario["quote"].id
    )
    assert err is None and invoice.contract_id is None
    supplier = _invoice_seller_company(invoice)
    assert supplier is not None
    assert supplier.id == scenario["seller"].id


@pytest.mark.django_db
def test_invoice_supplier_resolves_to_own_company_for_pure_manual(scenario):
    # D0: a pure-manual invoice (ad-hoc lines, no КП) still names the seller — the own company
    # (core.tenant.own_company_id), never «—».
    from crm.services.billing import _invoice_seller_company

    invoice, err = create_manual_invoice(
        scenario["solo_deal"].id,
        scenario["seller_user"],
        lines=[{"description": "Доставка", "quantity": 1, "unit_price_excl_vat": "150000.00"}],
    )
    assert err is None
    supplier = _invoice_seller_company(invoice)
    assert supplier is not None
    assert supplier.id == scenario["seller"].id


@pytest.mark.django_db
def test_manual_invoice_requires_a_line_source(scenario):
    invoice, err = create_manual_invoice(scenario["deal"].id, scenario["seller_user"])
    assert invoice is None
    assert err == "INVOICE_NO_LINES"


@pytest.mark.django_db
def test_draft_hidden_from_buyer_and_outsider_visible_to_staff(scenario):
    invoice, err = create_manual_invoice(
        scenario["deal"].id, scenario["seller_user"], source_quote_id=scenario["quote"].id
    )
    assert err is None

    def _seller_visible(user):
        q = _seller_side_q(user)
        if q is None:
            return set()
        return set(Invoice.objects.filter(q).values_list("pk", flat=True))

    # Own-company staff see the DRAFT.
    assert invoice.pk in _seller_visible(scenario["seller_user"])
    # An outsider (not own-company staff) must NOT see the DRAFT manual invoice.
    assert invoice.pk not in _seller_visible(scenario["outsider_user"])
    # Buyer has no seller company → the DRAFT is confined to the seller side.
    assert _seller_side_q(scenario["buyer_user"]) is None


@pytest.mark.django_db
def test_issue_cancel_lifecycle_and_payment_guard(scenario):
    invoice, err = create_manual_invoice(
        scenario["deal"].id, scenario["seller_user"], source_quote_id=scenario["quote"].id
    )
    assert err is None

    # Payment rejects a DRAFT (F1 I-1 — no zombie PAID).
    _, pay_err = record_payment(invoice.id, actor=make_cashier(), amount=Decimal("100.00"), paid_at=date(2026, 7, 1))
    assert pay_err == "INVOICE_NOT_ISSUED"

    # Issue → ISSUED (existing lifecycle, unchanged).
    issued, issue_err = issue_invoice(invoice, scenario["seller_user"])
    assert issue_err is None
    assert issued.status_code == "ISSUED"

    # Cancel a fresh manual DRAFT works too (pure-manual — allowed).
    fresh, fresh_err = create_manual_invoice(
        scenario["solo_deal"].id,
        scenario["seller_user"],
        lines=[{"description": "X", "quantity": 1, "unit_price_excl_vat": "1000.00"}],
    )
    assert fresh_err is None
    cancelled, cancel_err = cancel_invoice(fresh, scenario["seller_user"])
    assert cancel_err is None
    assert cancelled.status_code == "CANCELLED"
