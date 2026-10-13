"""SEC audit #4 — per-seller chat + timeline lane isolation on a multi-seller RFQ.

Self-contained fixtures (not shared with test_ms_routing.py) so this file never conflicts
with other sec-PRs appending to the routing suite. A competing seller B must never read
seller A's private buyer↔A chat lane or A's lane timeline events.
"""

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import Company, CompanyMember, CompanyType, CustomUser, WorkspaceRole
from crm.models import Deal, DealSellerRouting, DealStage


@pytest.fixture
def lookups(db):
    WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})
    CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Client", "sort_order": 10})
    CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 20})
    for code in ("DRAFT", "RFQ_OPEN"):
        DealStage.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})


def _seller(name, inn, email):
    company = Company.objects.create(name=name, inn=inn)
    company.types.add(CompanyType.objects.get(code="SUPPLIER"))
    user = CustomUser.objects.create_user(email=email, username=email, password="x")
    CompanyMember.objects.create(
        user=user,
        company=company,
        role=WorkspaceRole.objects.get(code="OWNER"),
        is_active=True,
        is_primary=True,
        can_sell=True,
    )
    return user, company


def _buyer(email, buyer_co):
    user = CustomUser.objects.create_user(email=email, username=email, password="x")
    CompanyMember.objects.create(
        user=user,
        company=buyer_co,
        role=WorkspaceRole.objects.get(code="OWNER"),
        is_active=True,
        is_primary=True,
        can_buy=True,
    )
    return user


def _api(user, ctx="SELLER"):
    client = APIClient()
    client.credentials(
        HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}", HTTP_X_ACTIVE_CONTEXT=ctx
    )
    return client


@pytest.fixture
def world(lookups):
    sa_user, sa_co = _seller("Seller A", "A100", "sa@lane.test")
    sb_user, sb_co = _seller("Seller B", "B100", "sb@lane.test")
    buyer_co = Company.objects.create(name="Buyer Co", inn="C100")
    buyer_co.types.add(CompanyType.objects.get(code="CLIENT"))
    return dict(sa_user=sa_user, sa_co=sa_co, sb_user=sb_user, sb_co=sb_co, buyer_co=buyer_co)


def _shared_deal(world):
    deal = Deal.objects.create(title="Shared", company=world["buyer_co"], stage=DealStage.objects.get(code="RFQ_OPEN"))
    DealSellerRouting.objects.create(deal=deal, seller_company=world["sa_co"])
    DealSellerRouting.objects.create(deal=deal, seller_company=world["sb_co"])
    return deal


def _msg_texts(resp):
    data = resp.json()
    rows = data["results"] if isinstance(data, dict) and "results" in data else data
    return {m["text"] for m in rows}


@pytest.mark.django_db
def test_chat_lanes_isolate_competing_sellers(world):
    """Seller B must never read seller A's private buyer↔A lane; a seller's message is
    auto-tagged to its own lane, the buyer addresses a specific lane."""
    deal = _shared_deal(world)

    ra = _api(world["sa_user"]).post("/api/v1/crm/messages/", {"deal": deal.id, "text": "Секрет A"}, format="json")
    assert ra.status_code == 201, ra.content
    assert ra.json()["seller_company"] == world["sa_co"].id

    buyer_user = _buyer("buyerchat@lane.test", world["buyer_co"])
    no_lane = _api(buyer_user, ctx="BUYER").post(
        "/api/v1/crm/messages/", {"deal": deal.id, "text": "No lane"}, format="json"
    )
    assert no_lane.status_code == 400
    assert no_lane.json()["detail"] == "MESSAGE_LANE_REQUIRED"
    rb = _api(buyer_user, ctx="BUYER").post(
        "/api/v1/crm/messages/",
        {"deal": deal.id, "text": "Ответ A", "seller_company": world["sa_co"].id},
        format="json",
    )
    assert rb.status_code == 201, rb.content
    assert rb.json()["seller_company"] == world["sa_co"].id

    assert "Секрет A" not in _msg_texts(_api(world["sb_user"]).get(f"/api/v1/crm/messages/?deal={deal.id}"))
    assert "Ответ A" not in _msg_texts(_api(world["sb_user"]).get(f"/api/v1/crm/messages/?deal={deal.id}"))
    assert "Секрет A" in _msg_texts(_api(world["sa_user"]).get(f"/api/v1/crm/messages/?deal={deal.id}"))


@pytest.mark.django_db
def test_timeline_lane_isolation(world):
    """A co-routed seller's «История» excludes a competitor's lane events."""
    deal = _shared_deal(world)
    _api(world["sa_user"]).post("/api/v1/crm/messages/", {"deal": deal.id, "text": "Событие A"}, format="json")

    def _details(user):
        rows = _api(user).get(f"/api/v1/crm/timeline/?deal_id={deal.id}").json()
        rows = rows["results"] if isinstance(rows, dict) and "results" in rows else rows
        return " ".join(r.get("detail", "") for r in rows)

    assert "Событие A" not in _details(world["sb_user"])
    assert "Событие A" in _details(world["sa_user"])
