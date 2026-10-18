"""Tests for the counterparty / deal activity timeline (CRM Phase A).

The timeline is a read surface over ActivityLog's new relation links (company / contact / deal).
The isolation contract mirrors the rest of CRM: deal timeline = the deal's access boundary;
company timeline = a member sees own org fully, own-company staff (the seller of every deal —
M1-ERP-02 wave 3) and the administrator see everything, anyone else gets an empty list.
"""

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import Company, CompanyMember, CompanyType, CustomUser, WorkspaceRole
from crm.models import ActivityLog, Deal, DealStage


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


def _api(user):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
    return client


@pytest.fixture
def scene(lookups):
    buyer_co = _company("Buyer Co", "T100", "CLIENT")
    own_co = _company("Own Co", "T200", "SUPPLIER")
    other_client_co = _company("Other Client", "T300", "CLIENT")
    buyer = _member(buyer_co, "buyer@t.test")
    staff = _member(own_co, "staff@t.test", can_sell=True)
    # An outsider: a member of ANOTHER client company — not staff, not this deal's buyer.
    outsider = _member(other_client_co, "out@t.test")

    stage = DealStage.objects.get(code="DRAFT")
    deal_a = Deal.objects.create(title="Deal A", company=buyer_co, stage=stage)
    deal_b = Deal.objects.create(title="Deal B", company=buyer_co, stage=stage)

    ActivityLog.objects.create(action="Сделка создана", deal=deal_a, company=buyer_co)
    ActivityLog.objects.create(action="КП отправлено клиенту", deal=deal_a, company=buyer_co)
    ActivityLog.objects.create(action="Сделка создана", deal=deal_b, company=buyer_co)
    # Company-scoped event with NO deal (e.g. archiving).
    ActivityLog.objects.create(action="Компания архивирована", company=buyer_co)
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


def test_staff_sees_deal_timeline(scene):
    resp = _api(scene["staff"]).get(f"/api/v1/crm/timeline/?deal_id={scene['deal_a'].id}")
    assert resp.status_code == 200
    assert len(resp.json()) == 2
    assert all(entry["deal_id"] == scene["deal_a"].id for entry in resp.json())


def test_outsider_gets_403_on_deal_timeline(scene):
    resp = _api(scene["outsider"]).get(f"/api/v1/crm/timeline/?deal_id={scene['deal_a'].id}")
    assert resp.status_code == 403
    assert resp.json()["detail"] == "MEMBER_REQUIRED_FOR_ACTION"


# ── company scope ───────────────────────────────────────────────────────────


def test_member_sees_own_company_full_history(scene):
    resp = _api(scene["buyer"]).get(f"/api/v1/crm/timeline/?company_id={scene['buyer_co'].id}")
    assert resp.status_code == 200
    assert len(resp.json()) == 4  # both deals + the no-deal company event


def test_staff_sees_full_company_history(scene):
    """The seller of every deal is the own company: its staff see the counterparty's whole history —
    every deal plus company-level (no-deal) events."""
    resp = _api(scene["staff"]).get(f"/api/v1/crm/timeline/?company_id={scene['buyer_co'].id}")
    assert resp.status_code == 200
    entries = resp.json()
    assert len(entries) == 4
    assert {entry["deal_id"] for entry in entries} == {scene["deal_a"].id, scene["deal_b"].id, None}


def test_outsider_gets_empty_list_not_oracle(scene):
    """A user with no relationship to the company gets [] — same shape as 'nothing yet',
    so company ids can't be probed for existence."""
    resp = _api(scene["outsider"]).get(f"/api/v1/crm/timeline/?company_id={scene['buyer_co'].id}")
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
    _log_quote(quote, scene["staff"], "quote.submit_for_review")
    entry = ActivityLog.objects.get(action="quote.submit_for_review")
    assert entry.deal_id == scene["deal_a"].id
    assert entry.company_id == scene["buyer_co"].id
    assert entry.entity_type == "quote" and entry.entity_id == quote.id
