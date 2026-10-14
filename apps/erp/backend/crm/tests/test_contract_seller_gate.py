"""Seller-side gate on contract generation — after the platform monetisation was removed.

M1-ERP-02 wave 2 removed the paid-seller subscription gate (`SUBSCRIPTION_REQUIRED`): a seller
team acts by its role and its routing to the deal, not by a paid plan. What stays: the actor
must be on the seller side, and bound to THIS deal's routing (SEC audit #1).
"""

import pytest

from accounts.models import Company, CompanyMember, CompanyType, CustomUser, WorkspaceRole
from crm import services as crm_services
from crm.models import Quote


@pytest.fixture
def lookups(db):
    WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})
    CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 20})
    CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Client", "sort_order": 10})


def _seller_user(email="seller@gate.test", *, company_type="SUPPLIER"):
    """An OWNER with can_sell in a company of the given type."""
    company = Company.objects.create(
        name=f"Seller {email}",
        inn=email,
    )
    company.types.add(CompanyType.objects.get(code=company_type))
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
    return user, company


def test_seller_needs_no_subscription_to_generate_a_contract(lookups):
    """No paid plan exists any more: a seller clears the side gate and reaches the quote lookup."""
    user, _ = _seller_user(email="gc-ok@gate.test")
    with pytest.raises(Quote.DoesNotExist):
        crm_services.generate_contract_from_quote(999999, actor=user)


def test_buyer_side_member_cannot_generate_a_contract(lookups):
    """The side gate stays: a member of a buyer-only company is refused before any lookup."""
    user, _ = _seller_user(email="buyer@gate.test", company_type="CLIENT")
    contract, err = crm_services.generate_contract_from_quote(999999, actor=user)
    assert contract is None
    assert err == "MEMBER_REQUIRED_FOR_ACTION"


# ── SEC audit #1: routing bind — an unrouted seller can't touch the contract ──


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
    _, routed_co = _seller_user(email="routed@gate.test")
    _, quote = _deal_with_quote(routed_co)
    # A different seller NOT routed to this deal must be blocked.
    other_user, _ = _seller_user(email="other@gate.test")
    contract, err = crm_services.generate_contract_from_quote(quote.id, actor=other_user)
    assert contract is None
    assert err == "MEMBER_REQUIRED_FOR_ACTION"


def test_generate_contract_allows_routed_seller_past_bind(lookups):
    routed_user, routed_co = _seller_user(email="routed2@gate.test")
    _, quote = _deal_with_quote(routed_co)
    # Routed seller clears the bind → reaches the status check (DRAFT quote, not APPROVED/SENT).
    contract, err = crm_services.generate_contract_from_quote(quote.id, actor=routed_user)
    assert contract is None
    assert err == "CONTRACT_NEEDS_APPROVAL"
