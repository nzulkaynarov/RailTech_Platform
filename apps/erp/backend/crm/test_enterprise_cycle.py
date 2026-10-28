"""
Enterprise cycle tests — cover the Phase 2/3 business services and FSM gates.

Runs against the DB via pytest-django (see pytest.ini).
"""

from decimal import Decimal

import pytest
from django.utils import timezone
from integration.tests import world as w

from accounts.models import Company, CompanyMember, CompanyType, CustomUser, SystemRole, WorkspaceRole
from catalog.models import DomainType, ProductStatus, StockStatus
from crm import services as crm_services
from crm.models import (
    ActStatus,
    Contract,
    ContractStatus,
    Deal,
    DealStage,
    FulfillmentStatus,
    InvoiceStatus,
    Quote,
    QuoteItem,
    QuoteStatus,
)
from master_data.models import Country, Currency, UnitOfMeasure

# ─── Shared fixtures ──────────────────────────────────────────────────────


@pytest.fixture
def master_data(db):
    """Load the lookup tables needed by every test."""
    CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Client", "sort_order": 10})
    CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 20})
    WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})
    SystemRole.objects.get_or_create(code="USER", defaults={"name": "User", "sort_order": 10})
    SystemRole.objects.get_or_create(code="ADMIN", defaults={"name": "Platform Admin", "sort_order": 0})
    QuoteStatus.objects.get_or_create(code="DRAFT", defaults={"name": "Draft", "sort_order": 10})
    QuoteStatus.objects.get_or_create(code="SENT", defaults={"name": "Sent", "sort_order": 20})
    QuoteStatus.objects.get_or_create(code="APPROVED", defaults={"name": "Approved", "sort_order": 30})
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
    # Post-sale status lookups (F5.4) — --nomigrations skips the seeding migration.
    for code in ["DRAFT", "PENDING_CLIENT", "PENDING_MANAGER", "SIGNED", "CANCELLED"]:
        ContractStatus.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    for code in ["DRAFT", "ISSUED", "PARTIAL", "PAID", "OVERDUE", "CANCELLED"]:
        InvoiceStatus.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    for code in ["DRAFT", "ISSUED", "SIGNED", "CANCELLED"]:
        ActStatus.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    for code in ["PENDING", "SHIPPED", "IN_TRANSIT", "DELIVERED", "ACCEPTED", "DISPUTED"]:
        FulfillmentStatus.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    Country.objects.get_or_create(code="UZ", defaults={"name": "Uzbekistan", "sort_order": 10})
    Currency.objects.get_or_create(code="USD", defaults={"name": "US Dollar", "symbol": "$", "sort_order": 10})
    UnitOfMeasure.objects.get_or_create(code="PCS", defaults={"name": "Piece", "sort_order": 10})
    DomainType.objects.get_or_create(
        code="GENERAL_GOODS", defaults={"name": "General goods", "sku_prefix": "GG", "sort_order": 10}
    )
    ProductStatus.objects.get_or_create(code="PUBLISHED", defaults={"name": "Published", "sort_order": 20})
    StockStatus.objects.get_or_create(code="IN_STOCK", defaults={"name": "In stock", "sort_order": 10})


@pytest.fixture
def buyer(master_data):
    user = CustomUser.objects.create_user(
        email="t.buyer@example.com",
        username="t_buyer",
        password="pw",
        is_active=True,
        first_name="T",
        last_name="Buyer",
    )
    company = Company.objects.create(
        name="T Buyer LLC",
        inn="1000000001",
        # O3: продавец с платёжными реквизитами — иначе `issue_invoice` не выпустит счёт (он неоплатен).
        bank_account="20208000900001234567",
        mfo="00443",
    )
    company.types.add(CompanyType.objects.get(code="CLIENT"))
    CompanyMember.objects.create(
        user=user,
        company=company,
        role=WorkspaceRole.objects.get(code="OWNER"),
        is_primary=True,
        is_active=True,
    )
    return user, company


@pytest.fixture
def supplier(master_data):
    user = CustomUser.objects.create_user(
        email="t.supplier@example.com",
        username="t_supplier",
        password="pw",
        is_active=True,
        first_name="T",
        last_name="Supplier",
    )
    company = Company.objects.create(
        name="T Supplier LLC",
        inn="2000000002",
        # O3: продавец с платёжными реквизитами — иначе `issue_invoice` не выпустит счёт (он неоплатен).
        bank_account="20208000900001234567",
        mfo="00443",
    )
    company.types.add(CompanyType.objects.get(code="SUPPLIER"))
    CompanyMember.objects.create(
        user=user,
        company=company,
        role=WorkspaceRole.objects.get(code="OWNER"),
        is_primary=True,
        is_active=True,
    )
    return user, company


@pytest.fixture
def manager(master_data):
    # Test fixture acting as platform-side engineer (is_superuser bypasses every
    # per-company can_sell/can_buy check). Role is USER so the platform-admin
    # invariant from migration 0010 (ADMIN ⇒ no memberships) is not violated
    # when this fixture later becomes a Deal.manager — superuser is the proper
    # escape hatch for tests that need cross-company write access.
    return CustomUser.objects.create_user(
        email="t.manager@example.com",
        username="t_manager",
        password="pw",
        is_active=True,
        is_staff=True,
        is_superuser=True,
        first_name="T",
        last_name="Manager",
        role=SystemRole.objects.get(code="USER"),
    )


@pytest.fixture
def deal(master_data, buyer, manager):
    buyer_user, buyer_co = buyer
    return Deal.objects.create(
        title="T Deal",
        company=buyer_co,
        client=buyer_user,
        manager=manager,
        stage=DealStage.objects.get(code="DRAFT"),
    )


# ─── FSM transitions + Contract gate ──────────────────────────────────────


@pytest.mark.django_db
def test_deal_fsm_valid_draft_to_sourcing(deal, manager):
    d, err = crm_services.transition_deal_stage(deal, "SOURCING", actor=manager)
    assert err is None
    assert d.stage.code == "SOURCING"


@pytest.mark.django_db
def test_deal_fsm_rejects_invalid_jump(deal, manager):
    d, err = crm_services.transition_deal_stage(deal, "CLOSED_WON", actor=manager)
    assert d is None
    assert err == "FSM_TRANSITION_NOT_ALLOWED"


@pytest.mark.django_db
def test_closed_won_requires_signed_contract(master_data, deal, manager):
    """CLOSED_WON refuses without SIGNED contract, even if FSM allows the transition."""
    contract_signed_stage = DealStage.objects.get(code="CONTRACT_SIGNED")
    deal.stage = contract_signed_stage
    deal.save()
    d, err = crm_services.transition_deal_stage(deal, "CLOSED_WON", actor=manager)
    assert d is None
    assert err == "CLOSED_WON_REQUIRES_SIGNED_CONTRACT"


@pytest.mark.django_db
def test_closed_won_succeeds_with_signed_contract(master_data, deal, manager, buyer):
    buyer_user, _ = buyer
    # seed a fake signed contract
    Contract.objects.create(
        deal=deal,
        quote=_create_simple_quote(deal, manager),
        number="CT-TEST-1",
        status=ContractStatus.objects.get(code="SIGNED"),
        total_amount=Decimal("100.00"),
        client_signer=buyer_user,
        client_signed_at=timezone.now(),
        manager_signer=manager,
        manager_signed_at=timezone.now(),
    )
    deal.stage = DealStage.objects.get(code="CONTRACT_SIGNED")
    deal.save()
    d, err = crm_services.transition_deal_stage(deal, "CLOSED_WON", actor=manager)
    assert err is None
    assert d.stage.code == "CLOSED_WON"


def _create_simple_quote(deal, manager):
    return Quote.objects.create(
        deal=deal,
        version=1,
        status=QuoteStatus.objects.get(code="DRAFT"),
        prepared_by=manager,
        tax_country=Country.objects.get(code="UZ"),
        vat_rate=Decimal("12.00"),
        subtotal_excl_vat=Decimal("100.00"),
        vat_amount=Decimal("12.00"),
        total_incl_vat=Decimal("112.00"),
    )


# ─── Contract lifecycle ───────────────────────────────────────────────────


@pytest.mark.django_db
def test_contract_double_sign_becomes_signed(master_data, deal, manager, buyer):
    buyer_user, _ = buyer
    quote = _create_simple_quote(deal, manager)
    # force APPROVED quote
    quote.status = QuoteStatus.objects.get(code="APPROVED")
    quote.save()
    contract, err = crm_services.generate_contract_from_quote(quote.id, actor=manager)
    assert err is None
    contract, err = crm_services.sign_contract_by_client(contract.id, manager)
    assert err is None
    assert contract.status_code == "PENDING_MANAGER"
    contract = w.sign_via_scan(contract.id)  # подпись кликом закрыта (D2-5): оператор → скан
    assert contract.status_code == "SIGNED"


@pytest.mark.django_db
def test_cancel_signed_contract_fails(master_data, deal, manager, buyer):
    buyer_user, _ = buyer
    quote = _create_simple_quote(deal, manager)
    quote.status = QuoteStatus.objects.get(code="APPROVED")
    quote.save()
    contract, _ = crm_services.generate_contract_from_quote(quote.id, actor=manager)
    crm_services.sign_contract_by_client(contract.id, manager)
    w.sign_via_scan(contract.id)
    _, err = crm_services.cancel_contract(contract.id, manager, "test")
    assert err is not None


# ─── Invoice + Payment + Act ──────────────────────────────────────────────


@pytest.mark.django_db
def test_record_payment_marks_invoice_paid(master_data, deal, manager, buyer):
    buyer_user, _ = buyer
    quote = _create_simple_quote(deal, manager)
    QuoteItem.objects.create(
        quote=quote,
        imported_raw_name="item",
        quantity=1,
        frozen_base_price=Decimal("100.00"),
        frozen_currency=Currency.objects.get(code="USD"),
        margin_percent=Decimal("0"),
        final_price_excl_vat=Decimal("100.00"),
    )
    quote.status = QuoteStatus.objects.get(code="APPROVED")
    quote.save()
    contract, _ = crm_services.generate_contract_from_quote(quote.id, actor=manager)
    crm_services.sign_contract_by_client(contract.id, manager)
    w.sign_via_scan(contract.id)
    invoice, err = crm_services.generate_invoice_from_contract(contract.id, actor=manager)
    assert err is None

    # Documents-2.0 F1 (I-1): an invoice is BORN a DRAFT and record_payment rejects a DRAFT
    # (no legal PDF / issue date yet) — so it must be ISSUED before it can be paid. This test
    # predates that change; issue it first, then pay.
    _, err = crm_services.issue_invoice(invoice, manager)
    assert err is None

    _, err = crm_services.record_payment(
        invoice.id,
        manager,
        amount=invoice.total_incl_vat,
        paid_at=timezone.localdate(),
        manual=True,
    )
    assert err is None
    invoice.refresh_from_db()
    assert invoice.status_code == "PAID"


@pytest.mark.django_db
def test_record_payment_rejects_negative(master_data, deal, manager, buyer):
    buyer_user, _ = buyer
    quote = _create_simple_quote(deal, manager)
    QuoteItem.objects.create(
        quote=quote,
        imported_raw_name="x",
        quantity=1,
        frozen_base_price=Decimal("100.00"),
        frozen_currency=Currency.objects.get(code="USD"),
        margin_percent=Decimal("0"),
        final_price_excl_vat=Decimal("100.00"),
    )
    quote.status = QuoteStatus.objects.get(code="APPROVED")
    quote.save()
    contract, _ = crm_services.generate_contract_from_quote(quote.id, actor=manager)
    crm_services.sign_contract_by_client(contract.id, manager)
    w.sign_via_scan(contract.id)
    invoice, _ = crm_services.generate_invoice_from_contract(contract.id, actor=manager)
    _, err = crm_services.record_payment(invoice.id, manager, amount="-1", paid_at=timezone.localdate())
    assert err is not None


# ─── Fulfillment auto CLOSED_WON ──────────────────────────────────────────


@pytest.mark.django_db
def test_fulfillment_accepted_auto_closes_deal(master_data, deal, manager, buyer):
    buyer_user, _ = buyer
    quote = _create_simple_quote(deal, manager)
    quote.status = QuoteStatus.objects.get(code="APPROVED")
    quote.save()
    contract, _ = crm_services.generate_contract_from_quote(quote.id, actor=manager)
    crm_services.sign_contract_by_client(contract.id, manager)
    w.sign_via_scan(contract.id)
    crm_services.ensure_fulfillment(deal)
    # Move deal to CONTRACT_SIGNED legally (via FSM hop DRAFT→SOURCING→CALCULATING→QUOTE_SENT→CONTRACT_SIGNED)
    for stage in ["SOURCING", "CALCULATING", "QUOTE_SENT", "CONTRACT_SIGNED"]:
        deal, err = crm_services.transition_deal_stage(deal, stage, actor=manager)
        assert err is None
    _, err = crm_services.update_fulfillment_status(deal.id, manager, "ACCEPTED")
    assert err is None
    deal.refresh_from_db()
    assert deal.stage.code == "CLOSED_WON"
