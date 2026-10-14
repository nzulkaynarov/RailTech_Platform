"""F0.2 — subscription gate on paid seller writes.

A SELLER team without an operational SupplierSubscription must be blocked from
the monetised seller actions (send КП, generate/sign contract, issue invoice/act)
with the stable `SUBSCRIPTION_REQUIRED` code. Superuser bypasses (DBA). The gate
fires *before* the target row is loaded, so these tests stay fixture-light.
"""

from datetime import timedelta

import pytest
from django.utils import timezone

from accounts.models import Company, CompanyMember, CompanyType, CustomUser, SupplierSubscription, WorkspaceRole
from accounts.services import assert_seller_can_operate
from crm import services as crm_services
from crm.models import Quote


@pytest.fixture
def lookups(db):
    WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})
    CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 20})
    CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Client", "sort_order": 10})


def _seller_user(email="seller@gate.test", *, with_subscription, operational=True):
    """A SUPPLIER-company OWNER with can_sell, optionally with a subscription."""
    company = Company.objects.create(
        name=f"Seller {email}",
        inn=email,
    )
    company.types.add(CompanyType.objects.get(code="SUPPLIER"))
    user = CustomUser.objects.create_user(email=email, username=email, password="x")
    CompanyMember.objects.create(
        user=user,
        company=company,
        role=WorkspaceRole.objects.get(code="OWNER"),
        is_active=True,
        is_primary=True,
        can_sell=True,
        can_buy=True,
    )
    if with_subscription:
        SupplierSubscription.objects.create(
            company=company,
            plan="PREMIUM",
            status="ACTIVE" if operational else "PAST_DUE",
            valid_until=timezone.localdate() + timedelta(days=30),
        )
    return user, company


# ── unit: assert_seller_can_operate ──────────────────────────────────────────


def test_seller_without_subscription_is_blocked(lookups):
    user, _ = _seller_user(with_subscription=False)
    assert assert_seller_can_operate(user) == "SUBSCRIPTION_REQUIRED"


def test_seller_with_operational_subscription_passes(lookups):
    user, _ = _seller_user(email="ok@gate.test", with_subscription=True, operational=True)
    assert assert_seller_can_operate(user) is None


def test_seller_with_past_due_subscription_is_blocked(lookups):
    user, _ = _seller_user(email="pastdue@gate.test", with_subscription=True, operational=False)
    assert assert_seller_can_operate(user) == "SUBSCRIPTION_REQUIRED"


def test_superuser_bypasses_subscription_gate(db):
    admin = CustomUser.objects.create_superuser(email="su@gate.test", username="su@gate.test", password="x")
    assert assert_seller_can_operate(admin) is None


# ── integration: the gate fires inside the seller-write services ─────────────


def test_generate_contract_blocked_without_subscription(lookups):
    """Gate runs before the Quote is loaded → SUBSCRIPTION_REQUIRED with a bogus id."""
    user, _ = _seller_user(email="gc-block@gate.test", with_subscription=False)
    contract, err = crm_services.generate_contract_from_quote(999999, actor=user)
    assert contract is None
    assert err == "SUBSCRIPTION_REQUIRED"


def test_generate_contract_passes_gate_with_subscription(lookups):
    """With an operational subscription the gate is cleared, so execution reaches
    the (missing) quote lookup and raises — i.e. it is NOT SUBSCRIPTION_REQUIRED."""
    user, _ = _seller_user(email="gc-ok@gate.test", with_subscription=True, operational=True)
    with pytest.raises(Quote.DoesNotExist):
        crm_services.generate_contract_from_quote(999999, actor=user)


# ── SEC audit #1: routing bind — an unrouted subscribed seller can't touch the contract ──


def _deal_with_quote(seller_company):
    """A buyer deal ROUTED to seller_company, carrying a DRAFT quote."""
    from decimal import Decimal

    from crm.models import Deal, DealSellerRouting, DealStage, QuoteStatus

    DealStage.objects.get_or_create(code="DRAFT", defaults={"name": "Draft", "sort_order": 10})
    QuoteStatus.objects.get_or_create(code="DRAFT", defaults={"name": "Draft", "sort_order": 10})
    buyer = Company.objects.create(name="Buyer sec1", inn=f"b{seller_company.id}")
    buyer.types.add(CompanyType.objects.get(code="CLIENT"))
    deal = Deal.objects.create(title="D", company=buyer, stage=DealStage.objects.get(code="DRAFT"))
    DealSellerRouting.objects.create(deal=deal, seller_company=seller_company)
    quote = Quote.objects.create(
        deal=deal,
        version=1,
        status=QuoteStatus.objects.get(code="DRAFT"),
        subtotal_excl_vat=Decimal("0"),
        vat_amount=Decimal("0"),
        total_incl_vat=Decimal("0"),
    )
    return deal, quote


def test_generate_contract_blocks_unrouted_seller(lookups):
    _, routed_co = _seller_user(email="routed@gate.test", with_subscription=True)
    _, quote = _deal_with_quote(routed_co)
    # A different subscribed seller NOT routed to this deal must be blocked.
    other_user, _ = _seller_user(email="other@gate.test", with_subscription=True)
    contract, err = crm_services.generate_contract_from_quote(quote.id, actor=other_user)
    assert contract is None
    assert err == "MEMBER_REQUIRED_FOR_ACTION"


def test_generate_contract_allows_routed_seller_past_bind(lookups):
    routed_user, routed_co = _seller_user(email="routed2@gate.test", with_subscription=True)
    _, quote = _deal_with_quote(routed_co)
    # Routed seller clears the bind → reaches the status check (DRAFT quote, not APPROVED/SENT).
    contract, err = crm_services.generate_contract_from_quote(quote.id, actor=routed_user)
    assert contract is None
    assert err == "CONTRACT_NEEDS_APPROVAL"
