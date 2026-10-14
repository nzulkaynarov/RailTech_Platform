"""SEC audit #7 — the generic change-stage endpoint must not be a parallel path around
submit_request's capability gate, and on the back-office side moving the pipeline is a
role permission (`quote.build`).

The seller of every deal is the own company (M1-ERP-02 wave 3): the multi-seller «shared deal»
close gate is gone — staff with the permission may decline (CLOSED_LOST) any deal, a view-only
role may not, an outsider does not even reach the deal.
"""

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import Company, CompanyMember, CompanyRole, CompanyType, CustomUser, WorkspaceRole
from crm.models import Deal, DealStage


@pytest.fixture
def lookups(db):
    WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})
    CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Client", "sort_order": 10})
    CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 20})
    for code in ("DRAFT", "RFQ_OPEN", "CLOSED_LOST"):
        DealStage.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})


def _member(company, email, *, company_roles=(), can_sell=False, can_buy=False):
    user = CustomUser.objects.create_user(email=email, username=email, password="x")
    CompanyMember.objects.create(
        user=user,
        company=company,
        role=WorkspaceRole.objects.get(code="OWNER"),
        company_roles=list(company_roles),
        is_active=True,
        is_primary=True,
        can_sell=can_sell,
        can_buy=can_buy,
    )
    return user


def _api(user):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
    return client


@pytest.fixture
def world(lookups):
    own = Company.objects.create(name="Own Co", inn="A100")
    own.types.add(CompanyType.objects.get(code="SUPPLIER"))
    buyer_co = Company.objects.create(name="Buyer Co", inn="C100")
    buyer_co.types.add(CompanyType.objects.get(code="CLIENT"))
    other_co = Company.objects.create(name="Other Client", inn="C200")
    other_co.types.add(CompanyType.objects.get(code="CLIENT"))
    viewer_role = CompanyRole.objects.create(company=own, name="Наблюдатель", permissions=[])
    manager_role = CompanyRole.objects.create(company=own, name="Сделки", permissions=["deal.manage"])
    return dict(
        staff=_member(own, "sa@cs.test", company_roles=[manager_role], can_sell=True),
        observer=_member(own, "obs@cs.test", company_roles=[viewer_role], can_sell=True),
        outsider=_member(other_co, "out@cs.test", can_sell=True),
        buyer_co=buyer_co,
    )


def _change_stage(user, deal, stage_code):
    return _api(user).post(f"/api/v1/crm/deals/{deal.id}/change-stage/", {"stage_code": stage_code}, format="json")


@pytest.mark.django_db
def test_change_stage_gates_staff_but_not_buyer(world):
    """change-stage must not bypass submit_request's buyer-capability gate for DRAFT→RFQ_OPEN.
    The KYC floor in front of it was removed in M1-ERP-02 wave 1c: the buyer passes."""
    draft = DealStage.objects.get(code="DRAFT")
    deal = Deal.objects.create(title="Draft RFQ", company=world["buyer_co"], stage=draft)

    r2 = _change_stage(world["staff"], deal, "RFQ_OPEN")
    assert r2.status_code == 403
    assert r2.json()["detail"] == "ONLY_BUYER_CAN_SUBMIT_REQUEST"

    buyer_user = _member(world["buyer_co"], "buyer7@cs.test", can_buy=True)
    r = _change_stage(buyer_user, deal, "RFQ_OPEN")
    # The user gate passes; what answers now is the FSM's own data guard (an empty заявка).
    assert r.status_code == 422, r.content
    assert r.json()["detail"] == "REQUEST_HAS_NO_ITEMS"


@pytest.mark.django_db
def test_staff_with_permission_may_decline_the_deal(world):
    """No «shared deal» any more: staff holding deal.manage closes the deal as lost."""
    deal = Deal.objects.create(title="RFQ", company=world["buyer_co"], stage=DealStage.objects.get(code="RFQ_OPEN"))
    r = _change_stage(world["staff"], deal, "CLOSED_LOST")
    assert r.status_code == 200, r.content
    deal.refresh_from_db()
    assert deal.stage.code == "CLOSED_LOST"


@pytest.mark.django_db
def test_view_only_staff_cannot_move_the_deal(world):
    deal = Deal.objects.create(title="RFQ", company=world["buyer_co"], stage=DealStage.objects.get(code="RFQ_OPEN"))
    r = _change_stage(world["observer"], deal, "CLOSED_LOST")
    assert r.status_code == 403, r.content
    assert r.json()["detail"] == "ROLE_NOT_PERMITTED"
    deal.refresh_from_db()
    assert deal.stage.code == "RFQ_OPEN"


@pytest.mark.django_db
def test_outsider_does_not_reach_the_deal(world):
    deal = Deal.objects.create(title="RFQ", company=world["buyer_co"], stage=DealStage.objects.get(code="RFQ_OPEN"))
    r = _change_stage(world["outsider"], deal, "CLOSED_LOST")
    assert r.status_code == 404, r.content
    deal.refresh_from_db()
    assert deal.stage.code == "RFQ_OPEN"
