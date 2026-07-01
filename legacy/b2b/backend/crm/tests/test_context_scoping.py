"""Confidentiality: deal visibility is scoped to the ACTING context.

Reported 2026-06-19: a user who is both a seller and a buyer, while in the BUYER
context, saw every buyer's заявка (because is_seller() grants the see-all
queryset regardless of the frontend context). The X-Active-Context header now
lets the backend narrow a seller to its own company while it acts as a buyer.
"""

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import Company, CompanyMember, CompanyType, CustomUser, VerificationStatus, WorkspaceRole
from crm.models import Deal, DealStage


@pytest.fixture
def lookups(db):
    WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})
    CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Client", "sort_order": 10})
    CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 20})
    VerificationStatus.objects.get_or_create(code="L2_VERIFIED", defaults={"name": "L2"})
    DealStage.objects.get_or_create(code="DRAFT", defaults={"name": "Draft", "sort_order": 10})


def _member(company, email, *, can_sell, can_buy):
    user = CustomUser.objects.create_user(email=email, username=email, password="x")
    CompanyMember.objects.create(
        user=user,
        company=company,
        role=WorkspaceRole.objects.get(code="OWNER"),
        is_active=True,
        is_primary=True,
        can_sell=can_sell,
        can_buy=can_buy,
    )
    return user


def _client(user, ctx=None):
    c = APIClient()
    creds = {"HTTP_AUTHORIZATION": f"Bearer {RefreshToken.for_user(user).access_token}"}
    if ctx:
        creds["HTTP_X_ACTIVE_CONTEXT"] = ctx
    c.credentials(**creds)
    return c


@pytest.fixture
def world(lookups):
    l2 = VerificationStatus.objects.get(code="L2_VERIFIED")
    draft = DealStage.objects.get(code="DRAFT")
    # A dual seller+buyer (SUPPLIER company, can_sell + can_buy) and its own deal.
    seller_co = Company.objects.create(name="Seller Co", inn="S1", verification_status=l2)
    seller_co.types.add(CompanyType.objects.get(code="SUPPLIER"))
    dual = _member(seller_co, "dual@t.test", can_sell=True, can_buy=True)
    own_deal = Deal.objects.create(title="own", company=seller_co, client=dual, stage=draft)
    # A separate buyer with its own заявка.
    buyer_co = Company.objects.create(name="Buyer Co", inn="B1", verification_status=l2)
    buyer_co.types.add(CompanyType.objects.get(code="CLIENT"))
    buyer = _member(buyer_co, "buyer@t.test", can_sell=False, can_buy=True)
    other_deal = Deal.objects.create(title="other", company=buyer_co, client=buyer, stage=draft)
    # A seller-owned КП (on the seller company's own deal) that a pure buyer must never see,
    # so the invariant can be asserted on /crm/quotes/ too — not just /crm/deals/.
    from crm.models import Quote, QuoteStatus

    qs_draft = QuoteStatus.objects.get_or_create(code="DRAFT", defaults={"name": "Draft", "sort_order": 10})[0]
    seller_quote = Quote.objects.create(deal=own_deal, version=1, status=qs_draft)
    return {
        "dual": dual,
        "buyer": buyer,
        "own_deal": own_deal,
        "other_deal": other_deal,
        "seller_quote": seller_quote,
    }


def _ids(resp):
    data = resp.json()
    rows = data["results"] if isinstance(data, dict) and "results" in data else data
    return {row["id"] for row in rows}


def test_seller_in_buyer_context_sees_only_own_company(world):
    """The reported bug: a dual user acting as BUYER must NOT see other buyers' заявки."""
    resp = _client(world["dual"], ctx="BUYER").get("/api/v1/crm/deals/")
    assert resp.status_code == 200
    ids = _ids(resp)
    assert world["own_deal"].id in ids
    assert world["other_deal"].id not in ids  # ← the leak, now closed


def test_seller_in_seller_context_sees_only_routed(world):
    """Multi-seller keystone: a seller in SELLER context sees the RFQs routed to it,
    NOT every buyer's заявка. A competitor's deal routed elsewhere stays invisible."""
    from accounts.models import Company, CompanyType
    from crm.models import Deal, DealSellerRouting, DealStage

    seller_co = world["dual"].memberships.first().company
    DealSellerRouting.objects.create(deal=world["other_deal"], seller_company=seller_co)
    # A competitor's RFQ, NOT routed to our seller → must stay hidden.
    comp_buyer = Company.objects.create(name="Comp Buyer", inn="C9")
    comp_buyer.types.add(CompanyType.objects.get(code="CLIENT"))
    competitor_deal = Deal.objects.create(
        title="competitor", company=comp_buyer, stage=DealStage.objects.get(code="DRAFT")
    )

    resp = _client(world["dual"], ctx="SELLER").get("/api/v1/crm/deals/")
    assert resp.status_code == 200
    ids = _ids(resp)
    assert world["other_deal"].id in ids  # routed to us → visible
    assert competitor_deal.id not in ids  # not routed to us → the leak, now closed


def test_seller_without_header_sees_only_routed(world):
    """Non-SPA clients (no X-Active-Context) still get the routing-scoped queryset —
    a missing header can no longer leak unrouted deals."""
    from crm.models import DealSellerRouting

    seller_co = world["dual"].memberships.first().company
    resp = _client(world["dual"]).get("/api/v1/crm/deals/")
    assert resp.status_code == 200
    assert world["other_deal"].id not in _ids(resp)  # unrouted → invisible
    DealSellerRouting.objects.create(deal=world["other_deal"], seller_company=seller_co)
    resp2 = _client(world["dual"]).get("/api/v1/crm/deals/")
    assert world["other_deal"].id in _ids(resp2)  # routed → now visible


def test_pure_buyer_never_sees_other_companies(world):
    """A pure buyer is scoped to its own company regardless of any header value."""
    for ctx in (None, "BUYER", "SELLER", "MANUFACTURER"):
        resp = _client(world["buyer"], ctx=ctx).get("/api/v1/crm/deals/")
        assert resp.status_code == 200
        ids = _ids(resp)
        assert world["other_deal"].id in ids  # own
        assert world["own_deal"].id not in ids  # seller_co's — never visible to a pure buyer


def test_pure_buyer_forged_header_sees_no_seller_quotes(world):
    """ADR-0005 Phase C contract: the invariant (is_seller() gates BEFORE the header is read)
    holds for /crm/quotes/ too — a pure buyer forging any context header sees ZERO seller-owned
    КП. This test must stay green through every Phase C slice (nav merge, page-derived context,
    switcher removal) — it is the guard that the unified shell can't leak seller data to a buyer."""
    for ctx in (None, "BUYER", "SELLER", "MANUFACTURER"):
        resp = _client(world["buyer"], ctx=ctx).get("/api/v1/crm/quotes/")
        assert resp.status_code == 200
        assert world["seller_quote"].id not in _ids(resp)  # seller's КП — never visible to a pure buyer
