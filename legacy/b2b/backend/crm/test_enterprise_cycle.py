"""
Enterprise cycle tests — cover the Phase 2/3 business services and FSM gates.

Runs against the DB via pytest-django (see pytest.ini).
"""
from decimal import Decimal
from datetime import timedelta

import pytest
from django.utils import timezone

from accounts.models import (
    CompanyType, Company, CompanyMember, CustomUser,
    SupplierSubscription, SystemRole, VerificationStatus, WorkspaceRole,
    CompanyRoleApplication,
)
from accounts import services as acc_services
from catalog.models import DomainType, Product, ProductStatus, StockStatus, SupplierOffer
from master_data.models import Country, Currency, UnitOfMeasure
from crm.models import (
    Act, Contract, Deal, DealStage, Fulfillment, Invoice, Payment,
    Quote, QuoteItem, QuoteStatus, SupplierBid,
)
from crm import services as crm_services
from crm.services import QuoteCalculationService, QuoteLifecycleService


# ─── Shared fixtures ──────────────────────────────────────────────────────


@pytest.fixture
def master_data(db):
    """Load the lookup tables needed by every test."""
    CompanyType.objects.get_or_create(code='CLIENT', defaults={'name': 'Client', 'sort_order': 10})
    CompanyType.objects.get_or_create(code='SUPPLIER', defaults={'name': 'Supplier', 'sort_order': 20})
    VerificationStatus.objects.get_or_create(code='L1_UNVERIFIED', defaults={'name': 'L1', 'sort_order': 10})
    VerificationStatus.objects.get_or_create(code='PROFILE_SUBMITTED', defaults={'name': 'Submitted', 'sort_order': 20})
    VerificationStatus.objects.get_or_create(code='L2_VERIFIED', defaults={'name': 'L2', 'sort_order': 30})
    WorkspaceRole.objects.get_or_create(code='OWNER', defaults={'name': 'Owner', 'sort_order': 10})
    SystemRole.objects.get_or_create(code='SALES_MANAGER', defaults={'name': 'SM', 'sort_order': 10, 'is_staff_level': True})
    QuoteStatus.objects.get_or_create(code='DRAFT', defaults={'name': 'Draft', 'sort_order': 10})
    QuoteStatus.objects.get_or_create(code='SENT', defaults={'name': 'Sent', 'sort_order': 20})
    QuoteStatus.objects.get_or_create(code='APPROVED', defaults={'name': 'Approved', 'sort_order': 30})
    for code in ['DRAFT', 'KYC_PENDING', 'RFQ_OPEN', 'SOURCING', 'CALCULATING',
                 'QUOTE_SENT', 'CONTRACT_SIGNED', 'CLOSED_WON', 'CLOSED_LOST']:
        DealStage.objects.get_or_create(code=code, defaults={'name': code, 'sort_order': 10})
    Country.objects.get_or_create(code='UZ', defaults={'name': 'Uzbekistan', 'sort_order': 10})
    Currency.objects.get_or_create(code='USD', defaults={'name': 'US Dollar', 'symbol': '$', 'sort_order': 10})
    UnitOfMeasure.objects.get_or_create(code='PCS', defaults={'name': 'Piece', 'sort_order': 10})
    DomainType.objects.get_or_create(code='GENERAL', defaults={'name': 'General', 'sku_prefix': 'GEN', 'sort_order': 10})
    ProductStatus.objects.get_or_create(code='PUBLISHED', defaults={'name': 'Published', 'sort_order': 20})
    StockStatus.objects.get_or_create(code='IN_STOCK', defaults={'name': 'In stock', 'sort_order': 10})


@pytest.fixture
def buyer(master_data):
    user = CustomUser.objects.create_user(
        email='t.buyer@example.com', username='t_buyer', password='pw', is_active=True,
        first_name='T', last_name='Buyer',
    )
    company = Company.objects.create(
        name='T Buyer LLC', inn='1000000001',
        verification_status=VerificationStatus.objects.get(code='L2_VERIFIED'),
    )
    company.types.add(CompanyType.objects.get(code='CLIENT'))
    CompanyMember.objects.create(
        user=user, company=company,
        role=WorkspaceRole.objects.get(code='OWNER'),
        is_primary=True, is_active=True,
    )
    return user, company


@pytest.fixture
def supplier(master_data):
    user = CustomUser.objects.create_user(
        email='t.supplier@example.com', username='t_supplier', password='pw', is_active=True,
        first_name='T', last_name='Supplier',
    )
    company = Company.objects.create(
        name='T Supplier LLC', inn='2000000002',
        verification_status=VerificationStatus.objects.get(code='L2_VERIFIED'),
    )
    company.types.add(CompanyType.objects.get(code='SUPPLIER'))
    CompanyMember.objects.create(
        user=user, company=company,
        role=WorkspaceRole.objects.get(code='OWNER'),
        is_primary=True, is_active=True,
    )
    return user, company


@pytest.fixture
def manager(master_data):
    return CustomUser.objects.create_user(
        email='t.manager@example.com', username='t_manager', password='pw',
        is_active=True, is_staff=True,
        first_name='T', last_name='Manager',
        role=SystemRole.objects.get(code='SALES_MANAGER'),
    )


@pytest.fixture
def deal(master_data, buyer, manager):
    buyer_user, buyer_co = buyer
    return Deal.objects.create(
        title='T Deal', company=buyer_co, client=buyer_user, manager=manager,
        stage=DealStage.objects.get(code='DRAFT'),
    )


# ─── Subscription lifecycle ───────────────────────────────────────────────


@pytest.mark.django_db
def test_ensure_trial_subscription_creates_30_day_trial(supplier):
    _, company = supplier
    sub = acc_services.ensure_trial_subscription(company)
    assert sub.status == 'TRIAL'
    assert sub.valid_until is not None
    assert sub.is_operational is True


@pytest.mark.django_db
def test_subscription_expires_to_past_due(supplier):
    _, company = supplier
    sub = acc_services.ensure_trial_subscription(company)
    sub.valid_until = timezone.now().date() - timedelta(days=1)
    sub.save()
    result = acc_services.check_and_expire_subscriptions()
    assert result['past_due'] >= 1
    sub.refresh_from_db()
    assert sub.status == 'PAST_DUE'
    assert sub.is_operational is False


@pytest.mark.django_db
def test_subscription_past_due_suspends_after_14_days(supplier):
    _, company = supplier
    sub = acc_services.ensure_trial_subscription(company)
    sub.status = 'PAST_DUE'
    sub.valid_until = timezone.now().date() - timedelta(days=20)
    sub.save()
    result = acc_services.check_and_expire_subscriptions()
    assert result['suspended'] >= 1
    sub.refresh_from_db()
    assert sub.status == 'SUSPENDED'


@pytest.mark.django_db
def test_record_subscription_payment_extends_and_activates(supplier, manager):
    _, company = supplier
    sub = acc_services.ensure_trial_subscription(company)
    initial_until = sub.valid_until
    sub = acc_services.record_subscription_payment(sub, '100.00', months=2, actor=manager, manual=True)
    assert sub.status == 'ACTIVE'
    assert sub.valid_until > initial_until


# ─── FSM transitions + Contract gate ──────────────────────────────────────


@pytest.mark.django_db
def test_deal_fsm_valid_draft_to_sourcing(deal, manager):
    d, err = crm_services.transition_deal_stage(deal, 'SOURCING', actor=manager)
    assert err is None
    assert d.stage.code == 'SOURCING'


@pytest.mark.django_db
def test_deal_fsm_rejects_invalid_jump(deal, manager):
    d, err = crm_services.transition_deal_stage(deal, 'CLOSED_WON', actor=manager)
    assert d is None
    assert 'not allowed' in err


@pytest.mark.django_db
def test_closed_won_requires_signed_contract(master_data, deal, manager):
    """CLOSED_WON refuses without SIGNED contract, even if FSM allows the transition."""
    contract_signed_stage = DealStage.objects.get(code='CONTRACT_SIGNED')
    deal.stage = contract_signed_stage
    deal.save()
    d, err = crm_services.transition_deal_stage(deal, 'CLOSED_WON', actor=manager)
    assert d is None
    assert 'подписанный контракт' in err.lower()


@pytest.mark.django_db
def test_closed_won_succeeds_with_signed_contract(master_data, deal, manager, buyer):
    buyer_user, _ = buyer
    # seed a fake signed contract
    Contract.objects.create(
        deal=deal, quote=_create_simple_quote(deal, manager),
        number='CT-TEST-1', status='SIGNED',
        total_amount=Decimal('100.00'),
        client_signer=buyer_user, client_signed_at=timezone.now(),
        manager_signer=manager, manager_signed_at=timezone.now(),
    )
    deal.stage = DealStage.objects.get(code='CONTRACT_SIGNED')
    deal.save()
    d, err = crm_services.transition_deal_stage(deal, 'CLOSED_WON', actor=manager)
    assert err is None
    assert d.stage.code == 'CLOSED_WON'


def _create_simple_quote(deal, manager):
    return Quote.objects.create(
        deal=deal, version=1,
        status=QuoteStatus.objects.get(code='DRAFT'),
        prepared_by=manager,
        tax_country=Country.objects.get(code='UZ'),
        vat_rate=Decimal('12.00'),
        subtotal_excl_vat=Decimal('100.00'),
        vat_amount=Decimal('12.00'),
        total_incl_vat=Decimal('112.00'),
    )


# ─── Contract lifecycle ───────────────────────────────────────────────────


@pytest.mark.django_db
def test_contract_double_sign_becomes_signed(master_data, deal, manager, buyer):
    buyer_user, _ = buyer
    quote = _create_simple_quote(deal, manager)
    # force APPROVED quote
    quote.status = QuoteStatus.objects.get(code='APPROVED')
    quote.save()
    contract, err = crm_services.generate_contract_from_quote(quote.id, actor=manager)
    assert err is None
    contract, err = crm_services.sign_contract_by_client(contract.id, buyer_user)
    assert err is None
    assert contract.status == 'PENDING_MANAGER'
    contract, err = crm_services.sign_contract_by_manager(contract.id, manager)
    assert err is None
    assert contract.status == 'SIGNED'


@pytest.mark.django_db
def test_cancel_signed_contract_fails(master_data, deal, manager, buyer):
    buyer_user, _ = buyer
    quote = _create_simple_quote(deal, manager)
    quote.status = QuoteStatus.objects.get(code='APPROVED')
    quote.save()
    contract, _ = crm_services.generate_contract_from_quote(quote.id, actor=manager)
    crm_services.sign_contract_by_client(contract.id, buyer_user)
    crm_services.sign_contract_by_manager(contract.id, manager)
    _, err = crm_services.cancel_contract(contract.id, manager, 'test')
    assert err is not None


# ─── Invoice + Payment + Act ──────────────────────────────────────────────


@pytest.mark.django_db
def test_record_payment_marks_invoice_paid(master_data, deal, manager, buyer):
    buyer_user, _ = buyer
    quote = _create_simple_quote(deal, manager)
    QuoteItem.objects.create(
        quote=quote, imported_raw_name='item',
        quantity=1, frozen_base_price=Decimal('100.00'),
        frozen_currency=Currency.objects.get(code='USD'),
        margin_percent=Decimal('0'),
        final_price_excl_vat=Decimal('100.00'),
    )
    quote.status = QuoteStatus.objects.get(code='APPROVED')
    quote.save()
    contract, _ = crm_services.generate_contract_from_quote(quote.id, actor=manager)
    crm_services.sign_contract_by_client(contract.id, buyer_user)
    crm_services.sign_contract_by_manager(contract.id, manager)
    invoice, err = crm_services.generate_invoice_from_contract(contract.id, actor=manager)
    assert err is None

    _, err = crm_services.record_payment(
        invoice.id, manager, amount=invoice.total_incl_vat,
        paid_at=timezone.now().date(), manual=True,
    )
    assert err is None
    invoice.refresh_from_db()
    assert invoice.status == 'PAID'


@pytest.mark.django_db
def test_record_payment_rejects_negative(master_data, deal, manager, buyer):
    buyer_user, _ = buyer
    quote = _create_simple_quote(deal, manager)
    QuoteItem.objects.create(
        quote=quote, imported_raw_name='x', quantity=1,
        frozen_base_price=Decimal('100.00'),
        frozen_currency=Currency.objects.get(code='USD'),
        margin_percent=Decimal('0'), final_price_excl_vat=Decimal('100.00'),
    )
    quote.status = QuoteStatus.objects.get(code='APPROVED')
    quote.save()
    contract, _ = crm_services.generate_contract_from_quote(quote.id, actor=manager)
    crm_services.sign_contract_by_client(contract.id, buyer_user)
    crm_services.sign_contract_by_manager(contract.id, manager)
    invoice, _ = crm_services.generate_invoice_from_contract(contract.id, actor=manager)
    _, err = crm_services.record_payment(invoice.id, manager, amount='-1', paid_at=timezone.now().date())
    assert err is not None


# ─── Fulfillment auto CLOSED_WON ──────────────────────────────────────────


@pytest.mark.django_db
def test_fulfillment_accepted_auto_closes_deal(master_data, deal, manager, buyer):
    buyer_user, _ = buyer
    quote = _create_simple_quote(deal, manager)
    quote.status = QuoteStatus.objects.get(code='APPROVED')
    quote.save()
    contract, _ = crm_services.generate_contract_from_quote(quote.id, actor=manager)
    crm_services.sign_contract_by_client(contract.id, buyer_user)
    crm_services.sign_contract_by_manager(contract.id, manager)
    crm_services.ensure_fulfillment(deal)
    # Move deal to CONTRACT_SIGNED legally (via FSM hop DRAFT→SOURCING→CALCULATING→QUOTE_SENT→CONTRACT_SIGNED)
    for stage in ['SOURCING', 'CALCULATING', 'QUOTE_SENT', 'CONTRACT_SIGNED']:
        deal, err = crm_services.transition_deal_stage(deal, stage, actor=manager)
        assert err is None
    _, err = crm_services.update_fulfillment_status(deal.id, manager, 'ACCEPTED')
    assert err is None
    deal.refresh_from_db()
    assert deal.stage.code == 'CLOSED_WON'


# ─── Supplier bidding ─────────────────────────────────────────────────────


@pytest.mark.django_db
def test_submit_bid_only_when_rfq_open(master_data, deal, manager, supplier):
    _, supplier_co = supplier
    _, err = crm_services.submit_supplier_bid(
        deal_id=deal.id, supplier_id=supplier_co.id, submitted_by=manager,
        items=[{'description': 'X', 'quantity': 1, 'unit_price': '10.00'}],
    )
    assert err is not None  # deal is DRAFT, not RFQ_OPEN


@pytest.mark.django_db
def test_accept_bid_moves_deal_to_calculating(master_data, deal, manager, supplier):
    _, supplier_co = supplier
    _, err = crm_services.open_rfq(deal.id, manager, supplier_ids=[supplier_co.id])
    assert err is None
    bid, err = crm_services.submit_supplier_bid(
        deal_id=deal.id, supplier_id=supplier_co.id, submitted_by=manager,
        items=[{'description': 'X', 'quantity': 1, 'unit_price': '10.00'}],
    )
    assert err is None
    bid, err = crm_services.accept_supplier_bid(bid.id, manager)
    assert err is None
    deal.refresh_from_db()
    assert deal.stage.code == 'CALCULATING'
