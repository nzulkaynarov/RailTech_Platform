"""Role/access model: the SELLER builds & owns the КП, the BUYER receives & approves it.

Locks down the inverted-ownership "каша" the audit found (2026-06-10):
  * building a Quote/КП is a seller (can_sell) action — was open to any authed user
    and effectively allowed the buyer (deal.company) while excluding the seller;
  * the seller sees buyer заявки/quotes to build them;
  * approve/reject require buyer can_buy (a КП approval = CONTRACT_SIGNED commitment).
"""

from decimal import Decimal

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import Company, CompanyMember, CompanyType, CustomUser, VerificationStatus, WorkspaceRole
from crm.models import Deal, DealStage, Quote, QuoteStatus

pytestmark = pytest.mark.django_db


@pytest.fixture
def lookups(db):
    for code in ["DRAFT", "SOURCING", "CALCULATING", "QUOTE_SENT", "CONTRACT_SIGNED", "CLOSED_LOST"]:
        DealStage.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    for code in ["DRAFT", "SENT", "APPROVED", "REJECTED"]:
        QuoteStatus.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})
    CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Client", "sort_order": 10})
    CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 20})
    VerificationStatus.objects.get_or_create(code="L2_VERIFIED", defaults={"name": "L2", "sort_order": 30})


def _api(user):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
    return client


def _member(company, email, *, can_sell=False, can_buy=False, role="OWNER"):
    user = CustomUser.objects.create_user(email=email, username=email.split("@")[0], password="pw", is_active=True)
    CompanyMember.objects.create(
        user=user,
        company=company,
        role=WorkspaceRole.objects.get(code=role),
        is_primary=True,
        is_active=True,
        can_sell=can_sell,
        can_buy=can_buy,
    )
    return user


@pytest.fixture
def seller(lookups):
    """RailTech — the single seller (SUPPLIER, can_sell)."""
    company = Company.objects.create(name="RailTech LLC", inn="7700000001")
    company.types.add(CompanyType.objects.get(code="SUPPLIER"))
    return _member(company, "seller@rt.test", can_sell=True), company


@pytest.fixture
def buyer(lookups):
    company = Company.objects.create(
        name="Buyer LLC", inn="3300000001", verification_status=VerificationStatus.objects.get(code="L2_VERIFIED")
    )
    company.types.add(CompanyType.objects.get(code="CLIENT"))
    return _member(company, "buyer@cl.test", can_buy=True), company


@pytest.fixture
def deal(buyer, seller):
    buyer_user, buyer_co = buyer
    _seller_user, seller_co = seller
    d = Deal.objects.create(
        title="Buyer заявка", company=buyer_co, client=buyer_user, stage=DealStage.objects.get(code="CALCULATING")
    )
    # Multi-seller routing: this RFQ is routed to RailTech (the seller) — that is
    # what grants the seller team visibility now (replaces the old see-all).
    from crm.models import DealSellerRouting

    DealSellerRouting.objects.create(deal=d, seller_company=seller_co)
    return d


def _quote(deal, status_code="DRAFT", prepared_by=None):
    return Quote.objects.create(
        deal=deal,
        version=1,
        status=QuoteStatus.objects.get(code=status_code),
        vat_rate=Decimal("12.00"),
        prepared_by=prepared_by,
        subtotal_excl_vat=Decimal("100"),
        vat_amount=Decimal("12"),
        total_incl_vat=Decimal("112"),
    )


# ── КП create = seller action ───────────────────────────────────────────────


def test_seller_can_build_quote_and_prepared_by_is_set(seller, deal):
    seller_user, _ = seller
    resp = _api(seller_user).post("/api/v1/crm/quotes/", {"deal": deal.id}, format="json")
    assert resp.status_code == 201, resp.data
    assert resp.data["prepared_by"] == seller_user.id  # server-stamped, never from the body


def test_buyer_cannot_build_quote(seller, buyer, deal):
    buyer_user, _ = buyer
    resp = _api(buyer_user).post("/api/v1/crm/quotes/", {"deal": deal.id}, format="json")
    assert resp.status_code == 403
    assert resp.data["detail"] == "ONLY_SELLER_CAN_BUILD_QUOTE"
    assert not Quote.objects.filter(deal=deal).exists()


def test_quote_create_is_not_open_to_any_authed_user(buyer, deal, lookups):
    """The old hole: a stranger (member of an unrelated company, no can_sell) could
    POST a quote onto someone else's deal. Now blocked."""
    other_co = Company.objects.create(name="Random LLC", inn="9900000009")
    other_co.types.add(CompanyType.objects.get(code="CLIENT"))
    stranger = _member(other_co, "stranger@x.test", can_buy=True)
    resp = _api(stranger).post("/api/v1/crm/quotes/", {"deal": deal.id}, format="json")
    assert resp.status_code == 403


# ── Visibility ──────────────────────────────────────────────────────────────


def test_seller_sees_buyer_quote(seller, deal):
    seller_user, _ = seller
    quote = _quote(deal)
    resp = _api(seller_user).get("/api/v1/crm/quotes/")
    ids = [q["id"] for q in (resp.data["results"] if isinstance(resp.data, dict) else resp.data)]
    assert quote.id in ids


# ── approve / reject = buyer can_buy ────────────────────────────────────────


def test_buyer_can_buy_approves_sent_quote(seller, buyer, deal):
    buyer_user, _ = buyer
    deal.stage = DealStage.objects.get(code="QUOTE_SENT")
    deal.save(update_fields=["stage"])
    quote = _quote(deal, status_code="SENT", prepared_by=seller[0])
    resp = _api(buyer_user).post(f"/api/v1/crm/quotes/{quote.id}/approve/")
    assert resp.status_code == 200, resp.data
    quote.refresh_from_db()
    assert quote.status.code == "APPROVED"


def test_seller_cannot_approve_quote(seller, deal):
    seller_user, _ = seller
    quote = _quote(deal, status_code="SENT", prepared_by=seller_user)
    resp = _api(seller_user).post(f"/api/v1/crm/quotes/{quote.id}/approve/")
    assert resp.status_code == 403
    assert resp.data["error"] == "MEMBER_REQUIRED_FOR_ACTION"


def test_buyer_without_can_buy_cannot_approve(buyer, deal):
    buyer_co = buyer[1]
    no_buy = _member(buyer_co, "nobuy@cl.test", can_buy=False)
    quote = _quote(deal, status_code="SENT")
    resp = _api(no_buy).post(f"/api/v1/crm/quotes/{quote.id}/approve/")
    assert resp.status_code == 403


# ── КП line items = seller action ───────────────────────────────────────────


def test_seller_can_add_quote_item_buyer_cannot(seller, buyer, deal):
    seller_user, _ = seller
    buyer_user, _ = buyer
    quote = _quote(deal)
    payload = {"quote": quote.id, "imported_raw_name": "Рельс Р65", "quantity": 5, "frozen_base_price": "100"}
    assert _api(buyer_user).post("/api/v1/crm/quote-items/", payload, format="json").status_code == 403
    assert _api(seller_user).post("/api/v1/crm/quote-items/", payload, format="json").status_code == 201


# ── contract generation guard (seller) ──────────────────────────────────────


def test_generate_contract_requires_seller(buyer):
    """Service-level guard: a non-seller actor is refused before any work."""
    from crm.services import generate_contract_from_quote

    buyer_user, _ = buyer
    _, err = generate_contract_from_quote(999, actor=buyer_user)
    assert err == "MEMBER_REQUIRED_FOR_ACTION"


# ── Tenant isolation regression (cross-tenant deal leak, 2026-06-11) ─────────
# CompanyMember.can_sell DEFAULTS to True, so a CLIENT member has can_sell=True
# out of the box. is_seller must NOT treat them as a seller, or they'd get the
# "see all deals" queryset and read every other tenant's заявки.


def test_client_with_default_can_sell_is_not_a_seller(buyer):
    from accounts.services.permissions import is_seller

    buyer_co = buyer[1]
    # Mimic the real default: a CLIENT member with can_sell=True.
    client_user = _member(buyer_co, "client-cansell@cl.test", can_sell=True, can_buy=True)
    assert is_seller(client_user) is False


def test_client_cannot_see_other_companies_deals(buyer, deal):
    """The reported leak: a new client saw foreign заявки."""
    other_co = Company.objects.create(name="Other Buyer LLC", inn="3300000099")
    other_co.types.add(CompanyType.objects.get(code="CLIENT"))
    other_client = _member(other_co, "other-buyer@cl.test", can_sell=True, can_buy=True)

    resp = _api(other_client).get("/api/v1/crm/deals/")
    ids = [d["id"] for d in (resp.data["results"] if isinstance(resp.data, dict) else resp.data)]
    assert deal.id not in ids  # deal belongs to a DIFFERENT buyer company


def test_real_seller_still_sees_all_deals(seller, deal):
    """The legitimate seller still sees an RFQ routed to it (the `deal` fixture routes
    to RailTech). Multi-seller scoping must not hide deals genuinely directed here."""
    resp = _api(seller[0]).get("/api/v1/crm/deals/")
    ids = [d["id"] for d in (resp.data["results"] if isinstance(resp.data, dict) else resp.data)]
    assert deal.id in ids
