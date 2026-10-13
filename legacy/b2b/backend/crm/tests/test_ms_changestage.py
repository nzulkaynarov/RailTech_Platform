"""SEC audit #7 — the generic change-stage endpoint must not be a parallel path around
submit_request's KYC/capability gates, nor let a co-routed seller close a shared deal.

Self-contained fixtures (not shared with test_ms_routing.py) so this file never conflicts
with other sec-PRs appending to the routing suite.
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
    for code in ("DRAFT", "RFQ_OPEN", "CLOSED_LOST"):
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
    sa_user, sa_co = _seller("Seller A", "A100", "sa@cs.test")
    sb_user, sb_co = _seller("Seller B", "B100", "sb@cs.test")
    buyer_co = Company.objects.create(name="Buyer Co", inn="C100")
    buyer_co.types.add(CompanyType.objects.get(code="CLIENT"))
    return dict(sa_user=sa_user, sa_co=sa_co, sb_user=sb_user, sb_co=sb_co, buyer_co=buyer_co)


@pytest.mark.django_db
def test_change_stage_gates_unverified_buyer_and_seller(world):
    """change-stage must not bypass submit_request's KYC + buyer-capability gates for
    DRAFT→RFQ_OPEN."""
    draft = DealStage.objects.get(code="DRAFT")
    deal = Deal.objects.create(title="Draft RFQ", company=world["buyer_co"], stage=draft)
    DealSellerRouting.objects.create(deal=deal, seller_company=world["sb_co"])

    buyer_user = _buyer("buyer7@cs.test", world["buyer_co"])
    r = _api(buyer_user, ctx="BUYER").post(
        f"/api/v1/crm/deals/{deal.id}/change-stage/", {"stage_code": "RFQ_OPEN"}, format="json"
    )
    assert r.status_code == 403, r.content
    assert r.json()["detail"] == "KYC_REQUIRED_TO_SUBMIT"

    r2 = _api(world["sb_user"]).post(
        f"/api/v1/crm/deals/{deal.id}/change-stage/", {"stage_code": "RFQ_OPEN"}, format="json"
    )
    assert r2.status_code == 403
    assert r2.json()["detail"] == "ONLY_BUYER_CAN_SUBMIT_REQUEST"


@pytest.mark.django_db
def test_change_stage_blocks_seller_closing_shared_deal(world):
    """A co-routed seller can't drive the SHARED multi-seller deal to CLOSED_LOST."""
    rfq = DealStage.objects.get(code="RFQ_OPEN")
    deal = Deal.objects.create(title="Shared", company=world["buyer_co"], stage=rfq)
    DealSellerRouting.objects.create(deal=deal, seller_company=world["sa_co"])
    DealSellerRouting.objects.create(deal=deal, seller_company=world["sb_co"])
    r = _api(world["sb_user"]).post(
        f"/api/v1/crm/deals/{deal.id}/change-stage/", {"stage_code": "CLOSED_LOST"}, format="json"
    )
    assert r.status_code == 403, r.content
    assert r.json()["detail"] == "ONLY_BUYER_CAN_CLOSE_SHARED_DEAL"
