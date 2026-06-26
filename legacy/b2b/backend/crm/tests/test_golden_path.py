"""
GOLDEN PATH — the single end-to-end regression net for the core business value.

This test drives the WHOLE product story through the real service layer, exactly
as buyer / seller / manager would trigger it from the UI:

    deal moves into CALCULATING  →  manager builds & sends the КП
    →  buyer approves it  →  contract is double-signed  →  invoice is issued
    →  payment is recorded  →  fulfillment accepted  →  deal CLOSED_WON.

If this test is green, the core flow the platform exists for works. If a future
change breaks any step, CI fails BEFORE it reaches production — this is the
"know it's stable" net that replaces clicking through prod by hand.

Runs against the DB via pytest-django (see pyproject.toml). Marked `integration`.
"""

from decimal import Decimal

import pytest
from django.utils import timezone

from accounts.models import (
    Company,
    CompanyMember,
    CompanyType,
    CustomUser,
    SystemRole,
    VerificationStatus,
    WorkspaceRole,
)
from catalog.models import DomainType, ProductStatus, StockStatus
from crm import services as crm_services
from crm.models import (
    ActStatus,
    ContractStatus,
    Deal,
    DealStage,
    FulfillmentStatus,
    InvoiceStatus,
    Quote,
    QuoteItem,
    QuoteStatus,
)
from crm.services.quotes import QuoteCalculationService, QuoteLifecycleService
from master_data.models import Country, Currency, UnitOfMeasure

# ─── Lookup + actor fixtures (self-contained, no shared conftest coupling) ────


@pytest.fixture
def lookups(db):
    """Seed every lookup code the golden path touches.

    Tests run with --nomigrations (pyproject addopts), so the data migration
    that normally seeds these (core/migrations/0002_seed_enterprise_lookups)
    never runs — we recreate the codes the flow asserts on.
    """
    for code in [
        "DRAFT",
        "KYC_PENDING",
        "RFQ_OPEN",
        "SOURCING",
        "CALCULATING",
        "QUOTE_SENT",
        "CONTRACT_SIGNED",
        "CLOSED_WON",
        "CLOSED_LOST",
    ]:
        DealStage.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    for code, name in [
        ("DRAFT", "Draft"),
        ("READY_TO_SEND", "Ready"),
        ("SENT", "Sent"),
        ("APPROVED", "Approved"),
        ("REJECTED", "Rejected"),
    ]:
        QuoteStatus.objects.get_or_create(code=code, defaults={"name": name, "sort_order": 10})
    CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Client", "sort_order": 10})
    CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 20})
    VerificationStatus.objects.get_or_create(code="L2_VERIFIED", defaults={"name": "L2", "sort_order": 30})
    WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})
    SystemRole.objects.get_or_create(code="USER", defaults={"name": "User", "sort_order": 10})
    Country.objects.get_or_create(code="UZ", defaults={"name": "Uzbekistan", "sort_order": 10})
    Currency.objects.get_or_create(code="USD", defaults={"name": "US Dollar", "symbol": "$", "sort_order": 10})
    UnitOfMeasure.objects.get_or_create(code="PCS", defaults={"name": "Piece", "sort_order": 10})
    DomainType.objects.get_or_create(
        code="GENERAL", defaults={"name": "General", "sku_prefix": "GEN", "sort_order": 10}
    )
    ProductStatus.objects.get_or_create(code="PUBLISHED", defaults={"name": "Published", "sort_order": 20})
    StockStatus.objects.get_or_create(code="IN_STOCK", defaults={"name": "In stock", "sort_order": 10})
    # Post-sale status lookups (F5.4) — seeded here because --nomigrations skips the
    # data migration that normally creates these rows.
    for code in ["DRAFT", "PENDING_CLIENT", "PENDING_MANAGER", "SIGNED", "CANCELLED"]:
        ContractStatus.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    for code in ["DRAFT", "ISSUED", "PARTIAL", "PAID", "OVERDUE", "CANCELLED"]:
        InvoiceStatus.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    for code in ["DRAFT", "ISSUED", "SIGNED", "CANCELLED"]:
        ActStatus.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    for code in ["PENDING", "SHIPPED", "IN_TRANSIT", "DELIVERED", "ACCEPTED", "DISPUTED"]:
        FulfillmentStatus.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})


def _make_company_with_owner(*, name, inn, type_code, email, username):
    user = CustomUser.objects.create_user(
        email=email,
        username=username,
        password="pw",
        is_active=True,
        first_name="T",
        last_name=type_code.title(),
    )
    company = Company.objects.create(
        name=name,
        inn=inn,
        verification_status=VerificationStatus.objects.get(code="L2_VERIFIED"),
    )
    company.types.add(CompanyType.objects.get(code=type_code))
    # OWNER membership; can_sell / can_buy default to True (see CompanyMember model).
    CompanyMember.objects.create(
        user=user,
        company=company,
        role=WorkspaceRole.objects.get(code="OWNER"),
        is_primary=True,
        is_active=True,
    )
    return user, company


@pytest.fixture
def buyer(lookups):
    return _make_company_with_owner(
        name="Golden Buyer LLC",
        inn="7700000001",
        type_code="CLIENT",
        email="g.buyer@example.com",
        username="g_buyer",
    )


@pytest.fixture
def manager(lookups):
    # Platform-side orchestrator. is_superuser bypasses per-company capability
    # checks; role USER keeps the migration-0010 invariant (ADMIN ⇒ no member).
    return CustomUser.objects.create_user(
        email="g.manager@example.com",
        username="g_manager",
        password="pw",
        is_active=True,
        is_staff=True,
        is_superuser=True,
        first_name="T",
        last_name="Manager",
        role=SystemRole.objects.get(code="USER"),
    )


@pytest.fixture
def deal(lookups, buyer, manager):
    buyer_user, buyer_co = buyer
    return Deal.objects.create(
        title="Golden Path Deal",
        company=buyer_co,
        client=buyer_user,
        manager=manager,
        stage=DealStage.objects.get(code="DRAFT"),
    )


def _build_quote_with_items(deal, manager):
    """Manager builds the КП: a draft quote with two priced line items."""
    quote = Quote.objects.create(
        deal=deal,
        version=1,
        status=QuoteStatus.objects.get(code="DRAFT"),
        prepared_by=manager,
        tax_country=Country.objects.get(code="UZ"),
        vat_rate=Decimal("12.00"),
        subtotal_excl_vat=Decimal("0"),
        vat_amount=Decimal("0"),
        total_incl_vat=Decimal("0"),
    )
    usd = Currency.objects.get(code="USD")
    QuoteItem.objects.create(
        quote=quote,
        imported_raw_name="Rail clamp KP-1",
        quantity=10,
        frozen_base_price=Decimal("100.00"),
        frozen_currency=usd,
        margin_percent=Decimal("20.00"),
        final_price_excl_vat=Decimal("0"),
    )
    QuoteItem.objects.create(
        quote=quote,
        imported_raw_name="Sleeper bolt M24",
        quantity=4,
        frozen_base_price=Decimal("50.00"),
        frozen_currency=usd,
        margin_percent=Decimal("10.00"),
        final_price_excl_vat=Decimal("0"),
    )
    # F3.8: margin is set ONCE on the whole КП (per-line margins above are now ignored by the engine).
    quote.margin_percent = Decimal("20.00")
    quote.save(update_fields=["margin_percent"])
    return quote


# ─── THE golden path ──────────────────────────────────────────────────────


@pytest.mark.integration
@pytest.mark.django_db
def test_golden_path_rfq_to_closed_won(deal, buyer, manager):
    """One test, the whole story. Each assert is a step the business depends on."""
    buyer_user, buyer_co = buyer

    # 1-3. Deal advances through the FSM into CALCULATING (DRAFT→SOURCING→CALCULATING).
    for target in ["SOURCING", "CALCULATING"]:
        moved, err = crm_services.transition_deal_stage(deal, target, actor=manager)
        assert err is None, f"transition_deal_stage → {target} failed: {err}"
    deal.refresh_from_db()
    assert deal.stage.code == "CALCULATING"

    # 4. Manager builds the КП and the calculation engine prices it.
    quote = _build_quote_with_items(deal, manager)
    quote = QuoteCalculationService.recalculate_quote(quote.id)
    # F3.8 КП-level margin 20%: 10×(100×1.20) + 4×(50×1.20) = 1200 + 240 = 1440 excl. VAT
    assert quote.subtotal_excl_vat == Decimal("1440.00"), quote.subtotal_excl_vat
    assert quote.vat_amount == Decimal("172.80")  # 12%
    assert quote.total_incl_vat == Decimal("1612.80")

    # 5. КП internally approved (chain is exercised in test_quote_approval_chain)
    #    → READY_TO_SEND, then sent to client → deal QUOTE_SENT, quote SENT, PDF.
    quote.status = QuoteStatus.objects.get(code="READY_TO_SEND")
    quote.save(update_fields=["status"])
    quote = QuoteLifecycleService.send_to_client(quote.id, manager)
    assert quote.status.code == "SENT"
    deal.refresh_from_db()
    assert deal.stage.code == "QUOTE_SENT"

    # 6. Buyer approves the КП → deal CONTRACT_SIGNED.
    quote = QuoteLifecycleService.approve_quote(quote.id, buyer_user)
    assert quote.status.code == "APPROVED"
    deal.refresh_from_db()
    assert deal.stage.code == "CONTRACT_SIGNED"

    # 7. Contract generated from the approved quote, then double-signed.
    contract, err = crm_services.generate_contract_from_quote(quote.id, actor=manager)
    assert err is None, f"generate_contract_from_quote failed: {err}"
    contract, err = crm_services.sign_contract_by_client(contract.id, buyer_user)
    assert err is None, f"sign_contract_by_client failed: {err}"
    assert contract.status_code == "PENDING_MANAGER"
    contract, err = crm_services.sign_contract_by_manager(contract.id, manager)
    assert err is None, f"sign_contract_by_manager failed: {err}"
    assert contract.status_code == "SIGNED"

    # 8. Invoice issued from the signed contract, then paid in full.
    invoice, err = crm_services.generate_invoice_from_contract(contract.id, actor=manager)
    assert err is None, f"generate_invoice_from_contract failed: {err}"
    _, err = crm_services.record_payment(
        invoice.id,
        manager,
        amount=invoice.total_incl_vat,
        paid_at=timezone.now().date(),
        manual=True,
    )
    assert err is None, f"record_payment failed: {err}"
    invoice.refresh_from_db()
    assert invoice.status_code == "PAID"

    # 9. Fulfillment accepted → deal auto-closes as CLOSED_WON. Story complete.
    crm_services.ensure_fulfillment(deal)
    _, err = crm_services.update_fulfillment_status(deal.id, manager, "ACCEPTED")
    assert err is None, f"update_fulfillment_status failed: {err}"
    deal.refresh_from_db()
    assert deal.stage.code == "CLOSED_WON"
