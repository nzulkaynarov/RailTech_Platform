"""Tests for the counterparty / deal activity timeline (CRM Phase A).

The timeline is a read surface over ActivityLog's new relation links (company / contact / deal).
The isolation contract mirrors the rest of CRM: deal timeline = deal-chat access boundary;
company timeline = member sees own org fully, a routed seller only events on deals visible to
them (multi-seller confidentiality), platform admin sees all.
"""

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import Company, CompanyMember, CompanyType, CustomUser, WorkspaceRole
from crm.models import ActivityLog, Deal, DealSellerRouting, DealStage


@pytest.fixture
def lookups(db):
    WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})
    CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Client", "sort_order": 10})
    CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 20})
    DealStage.objects.get_or_create(code="DRAFT", defaults={"name": "Draft", "sort_order": 10})


def _company(name, inn, type_code):
    company = Company.objects.create(name=name, inn=inn)
    company.types.add(CompanyType.objects.get(code=type_code))
    return company


def _member(company, email, **flags):
    user = CustomUser.objects.create_user(email=email, username=email, password="x", is_active=True)
    CompanyMember.objects.create(
        user=user,
        company=company,
        role=WorkspaceRole.objects.get(code="OWNER"),
        is_active=True,
        is_primary=True,
        **flags,
    )
    return user


def _api(user, ctx=None):
    client = APIClient()
    headers = {"HTTP_AUTHORIZATION": f"Bearer {RefreshToken.for_user(user).access_token}"}
    if ctx:
        headers["HTTP_X_ACTIVE_CONTEXT"] = ctx
    client.credentials(**headers)
    return client


@pytest.fixture
def scene(lookups):
    buyer_co = _company("Buyer Co", "T100", "CLIENT")
    seller_a_co = _company("Seller A", "T200", "SUPPLIER")
    seller_b_co = _company("Seller B", "T300", "SUPPLIER")
    buyer = _member(buyer_co, "buyer@t.test", can_buy=True)
    seller_a = _member(seller_a_co, "sa@t.test", can_sell=True)
    seller_b = _member(seller_b_co, "sb@t.test", can_sell=True)

    stage = DealStage.objects.get(code="DRAFT")
    deal_a = Deal.objects.create(title="Deal routed to A", company=buyer_co, stage=stage)
    DealSellerRouting.objects.create(deal=deal_a, seller_company=seller_a_co)
    deal_b = Deal.objects.create(title="Deal routed to B", company=buyer_co, stage=stage)
    DealSellerRouting.objects.create(deal=deal_b, seller_company=seller_b_co)

    ActivityLog.objects.create(action="Сделка создана", deal=deal_a, company=buyer_co)
    ActivityLog.objects.create(action="КП отправлено клиенту", deal=deal_a, company=buyer_co)
    ActivityLog.objects.create(action="Сделка создана", deal=deal_b, company=buyer_co)
    # Company-scoped event with NO deal (e.g. KYC) — sellers must not see it.
    ActivityLog.objects.create(action="KYC: подтверждение", company=buyer_co)
    return locals()


# ── param validation ────────────────────────────────────────────────────────


def test_timeline_requires_scope_param(scene):
    resp = _api(scene["buyer"]).get("/api/v1/crm/timeline/")
    assert resp.status_code == 400
    assert resp.json()["detail"] == "TIMELINE_SCOPE_REQUIRED"


def test_deal_timeline_unknown_deal_404(scene):
    resp = _api(scene["buyer"]).get("/api/v1/crm/timeline/?deal_id=999999")
    assert resp.status_code == 404


# ── deal scope ──────────────────────────────────────────────────────────────


def test_buyer_sees_own_deal_timeline(scene):
    resp = _api(scene["buyer"]).get(f"/api/v1/crm/timeline/?deal_id={scene['deal_a'].id}")
    assert resp.status_code == 200
    actions = [entry["action"] for entry in resp.json()]
    assert "КП отправлено клиенту" in actions and "Сделка создана" in actions
    assert all(entry["deal_id"] == scene["deal_a"].id for entry in resp.json())


def test_routed_seller_sees_deal_timeline(scene):
    resp = _api(scene["seller_a"], ctx="SELLER").get(f"/api/v1/crm/timeline/?deal_id={scene['deal_a'].id}")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


def test_unrouted_seller_gets_403_on_deal_timeline(scene):
    resp = _api(scene["seller_b"], ctx="SELLER").get(f"/api/v1/crm/timeline/?deal_id={scene['deal_a'].id}")
    assert resp.status_code == 403
    assert resp.json()["detail"] == "MEMBER_REQUIRED_FOR_ACTION"


# ── company scope ───────────────────────────────────────────────────────────


def test_member_sees_own_company_full_history(scene):
    resp = _api(scene["buyer"]).get(f"/api/v1/crm/timeline/?company_id={scene['buyer_co'].id}")
    assert resp.status_code == 200
    assert len(resp.json()) == 4  # both deals + the no-deal KYC event


def test_routed_seller_sees_only_own_deals_slice(scene):
    """Multi-seller confidentiality: seller A sees buyer-company events ONLY for deals routed
    to A — not B's deal, not company-internal (no-deal) events like KYC."""
    resp = _api(scene["seller_a"], ctx="SELLER").get(f"/api/v1/crm/timeline/?company_id={scene['buyer_co'].id}")
    assert resp.status_code == 200
    entries = resp.json()
    assert len(entries) == 2
    assert all(entry["deal_id"] == scene["deal_a"].id for entry in entries)


def test_outsider_gets_empty_list_not_oracle(scene):
    """A user with no relationship to the company gets [] — same shape as 'nothing yet',
    so company ids can't be probed for existence."""
    outsider_co = _company("Outsider", "T400", "SUPPLIER")
    outsider = _member(outsider_co, "out@t.test", can_sell=True)
    resp = _api(outsider, ctx="SELLER").get(f"/api/v1/crm/timeline/?company_id={scene['buyer_co'].id}")
    assert resp.status_code == 200
    assert resp.json() == []


def test_limit_is_applied_and_capped(scene):
    resp = _api(scene["buyer"]).get(f"/api/v1/crm/timeline/?company_id={scene['buyer_co'].id}&limit=1")
    assert len(resp.json()) == 1
    resp = _api(scene["buyer"]).get(f"/api/v1/crm/timeline/?company_id={scene['buyer_co'].id}&limit=99999")
    assert resp.status_code == 200  # capped at MAX_LIMIT, not an error


# ── producer wiring (quotes.py — this branch's own sites) ───────────────────


def test_log_quote_links_deal_and_company(scene):
    from crm.models import Quote, QuoteStatus
    from crm.services.quotes import _log_quote

    status = QuoteStatus.objects.get_or_create(code="DRAFT", defaults={"name": "Draft", "sort_order": 10})[0]
    quote = Quote.objects.create(deal=scene["deal_a"], version=1, status=status)
    _log_quote(quote, scene["seller_a"], "quote.submit_for_review")
    entry = ActivityLog.objects.get(action="quote.submit_for_review")
    assert entry.deal_id == scene["deal_a"].id
    assert entry.company_id == scene["buyer_co"].id
    assert entry.entity_type == "quote" and entry.entity_id == quote.id
