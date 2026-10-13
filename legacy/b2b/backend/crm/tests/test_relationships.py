"""Tests for the counterparty relationship book (CRM Phase B).

Edges are born from real interactions (RFQ routing / offline clients / offline deals), carry
denormalized rollups refreshed on deal-stage transitions, and are served by a strictly
owner-scoped API (multi-seller confidentiality: a book never leaks across owners).
"""

from decimal import Decimal

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import Company, CompanyMember, CompanyType, CustomUser, WorkspaceRole
from accounts.services.clients import create_offline_client
from crm.models import (
    CounterpartyRelationship,
    Deal,
    DealSellerRouting,
    DealStage,
    Quote,
    QuoteStatus,
    RelationshipDirection,
    RelationshipSource,
    RelationshipStage,
)
from crm.services.relationships import recompute_rollups_for_edge, touch_relationship


@pytest.fixture
def lookups(db):
    WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})
    CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Client", "sort_order": 10})
    CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 20})
    for code, order in (("DRAFT", 10), ("RFQ_OPEN", 20), ("CLOSED_WON", 90)):
        DealStage.objects.get_or_create(code=code, defaults={"name": code, "sort_order": order})
    for code, order in (("DRAFT", 10), ("APPROVED", 50)):
        QuoteStatus.objects.get_or_create(code=code, defaults={"name": code, "sort_order": order})


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
    buyer_co = _company("Buyer Co", "R100", "CLIENT")
    seller_co = _company("Seller Co", "R200", "SUPPLIER")
    other_seller_co = _company("Other Seller", "R300", "SUPPLIER")
    buyer = _member(buyer_co, "rb@t.test", can_buy=True)
    seller = _member(seller_co, "rs@t.test", can_sell=True)
    other_seller = _member(other_seller_co, "ro@t.test", can_sell=True)
    return locals()


# ── edge creation from interactions ─────────────────────────────────────────


def test_routing_creates_both_edges(scene):
    from crm.services.relationships import ensure_edges_for_deal_routing

    deal = Deal.objects.create(title="RFQ", company=scene["buyer_co"], stage=DealStage.objects.get(code="DRAFT"))
    ensure_edges_for_deal_routing(deal, [scene["seller_co"].id])

    buyer_edge = CounterpartyRelationship.objects.get(owner_company=scene["buyer_co"])
    assert buyer_edge.direction == RelationshipDirection.SUPPLIER
    assert buyer_edge.counterparty_company_id == scene["seller_co"].id
    assert buyer_edge.source == RelationshipSource.INBOUND_RFQ
    assert buyer_edge.first_interaction_at is not None

    seller_edge = CounterpartyRelationship.objects.get(owner_company=scene["seller_co"])
    assert seller_edge.direction == RelationshipDirection.CLIENT
    assert seller_edge.counterparty_company_id == scene["buyer_co"].id


def test_touch_is_idempotent_and_activates(scene):
    kwargs = dict(
        owner_company_id=scene["seller_co"].id,
        counterparty_company_id=scene["buyer_co"].id,
        direction=RelationshipDirection.CLIENT,
    )
    first = touch_relationship(**kwargs)
    assert first.stage == RelationshipStage.PROSPECT
    second = touch_relationship(**kwargs)
    assert second.pk == first.pk
    assert CounterpartyRelationship.objects.count() == 1
    second.refresh_from_db()
    assert second.stage == RelationshipStage.ACTIVE  # repeat interaction activates
    assert second.last_interaction_at >= first.first_interaction_at


def test_touch_refuses_self_edge(scene):
    assert (
        touch_relationship(
            owner_company_id=scene["seller_co"].id,
            counterparty_company_id=scene["seller_co"].id,
            direction=RelationshipDirection.CLIENT,
        )
        is None
    )


def test_lost_stage_is_not_resurrected_by_touch(scene):
    edge = touch_relationship(
        owner_company_id=scene["seller_co"].id,
        counterparty_company_id=scene["buyer_co"].id,
        direction=RelationshipDirection.CLIENT,
    )
    edge.stage = RelationshipStage.LOST
    edge.save(update_fields=["stage"])
    touch_relationship(
        owner_company_id=scene["seller_co"].id,
        counterparty_company_id=scene["buyer_co"].id,
        direction=RelationshipDirection.CLIENT,
    )
    edge.refresh_from_db()
    assert edge.stage == RelationshipStage.LOST


def test_offline_client_creates_client_edge(scene):
    result, err = create_offline_client(
        seller=scene["seller"],
        company_name="Offline Client LLC",
        contact_name="Иван Петров",
        email="ivan@offline.test",
    )
    assert err is None
    edge = CounterpartyRelationship.objects.get(owner_company=scene["seller_co"])
    assert edge.counterparty_company_id == result["company"].id
    assert edge.direction == RelationshipDirection.CLIENT
    assert edge.source == RelationshipSource.OFFLINE_CREATED


def test_offline_client_refused_for_non_seller(scene):
    result, err = create_offline_client(seller=scene["buyer"], company_name="X", contact_name="Y", email="x@y.test")
    assert result is None and err == "ONLY_SELLER_CAN_CREATE_CLIENTS"


# ── rollups ─────────────────────────────────────────────────────────────────


def test_rollups_count_deals_won_and_gmv(scene):
    from crm.services.relationships import ensure_edges_for_deal_routing

    won_stage = DealStage.objects.get(code="CLOSED_WON")
    open_stage = DealStage.objects.get(code="RFQ_OPEN")
    approved = QuoteStatus.objects.get(code="APPROVED")

    won_deal = Deal.objects.create(title="Won", company=scene["buyer_co"], stage=won_stage)
    DealSellerRouting.objects.create(deal=won_deal, seller_company=scene["seller_co"])
    Quote.objects.create(
        deal=won_deal,
        version=1,
        status=approved,
        seller_company=scene["seller_co"],
        total_incl_vat=Decimal("1500.00"),
    )
    open_deal = Deal.objects.create(title="Open", company=scene["buyer_co"], stage=open_stage)
    DealSellerRouting.objects.create(deal=open_deal, seller_company=scene["seller_co"])

    ensure_edges_for_deal_routing(won_deal, [scene["seller_co"].id])
    edge = CounterpartyRelationship.objects.get(
        owner_company=scene["seller_co"], direction=RelationshipDirection.CLIENT
    )
    recompute_rollups_for_edge(edge)
    edge.refresh_from_db()
    assert edge.deals_count == 2
    assert edge.won_count == 1
    assert edge.gmv == Decimal("1500.00")


def test_stage_transition_refreshes_rollups(scene):
    """transition_deal_stage is the live rollup trigger — CLOSED_WON bumps won_count."""
    from crm.models import Contract, ContractStatus
    from crm.services.deals import transition_deal_stage
    from crm.services.relationships import ensure_edges_for_deal_routing

    signed = ContractStatus.objects.get_or_create(code="SIGNED", defaults={"name": "Signed", "sort_order": 30})[0]
    deal = Deal.objects.create(title="Deal", company=scene["buyer_co"], stage=DealStage.objects.get(code="RFQ_OPEN"))
    DealSellerRouting.objects.create(deal=deal, seller_company=scene["seller_co"])
    ensure_edges_for_deal_routing(deal, [scene["seller_co"].id])
    quote = Quote.objects.create(
        deal=deal,
        version=1,
        status=QuoteStatus.objects.get(code="APPROVED"),
        seller_company=scene["seller_co"],
        total_incl_vat=Decimal("500.00"),
    )
    Contract.objects.create(deal=deal, quote=quote, status=signed)

    _, err = transition_deal_stage(deal, "CLOSED_WON", validate_fsm=False)
    assert err is None
    edge = CounterpartyRelationship.objects.get(
        owner_company=scene["seller_co"], direction=RelationshipDirection.CLIENT
    )
    assert edge.won_count == 1 and edge.deals_count == 1


# ── API scoping ─────────────────────────────────────────────────────────────


def test_relationship_list_is_owner_scoped(scene):
    touch_relationship(
        owner_company_id=scene["seller_co"].id,
        counterparty_company_id=scene["buyer_co"].id,
        direction=RelationshipDirection.CLIENT,
    )
    touch_relationship(
        owner_company_id=scene["other_seller_co"].id,
        counterparty_company_id=scene["buyer_co"].id,
        direction=RelationshipDirection.CLIENT,
    )
    resp = _api(scene["seller"], ctx="SELLER").get("/api/v1/crm/relationships/")
    assert resp.status_code == 200
    rows = resp.json()["results"] if isinstance(resp.json(), dict) else resp.json()
    assert len(rows) == 1
    assert rows[0]["counterparty"]["name"] == "Buyer Co"


def test_relationship_direction_filter(scene):
    touch_relationship(
        owner_company_id=scene["buyer_co"].id,
        counterparty_company_id=scene["seller_co"].id,
        direction=RelationshipDirection.SUPPLIER,
    )
    touch_relationship(
        owner_company_id=scene["buyer_co"].id,
        counterparty_company_id=scene["other_seller_co"].id,
        direction=RelationshipDirection.SUPPLIER,
    )
    api = _api(scene["buyer"])
    rows = api.get("/api/v1/crm/relationships/?direction=SUPPLIER").json()
    rows = rows["results"] if isinstance(rows, dict) else rows
    assert len(rows) == 2
    rows = api.get("/api/v1/crm/relationships/?direction=CLIENT").json()
    rows = rows["results"] if isinstance(rows, dict) else rows
    assert rows == []


def test_relationship_patch_stage_and_foreign_member_guard(scene):
    edge = touch_relationship(
        owner_company_id=scene["seller_co"].id,
        counterparty_company_id=scene["buyer_co"].id,
        direction=RelationshipDirection.CLIENT,
    )
    api = _api(scene["seller"], ctx="SELLER")
    resp = api.patch(f"/api/v1/crm/relationships/{edge.id}/", {"stage": "LOST"}, format="json")
    assert resp.status_code == 200 and resp.json()["stage"] == "LOST"
    # A member of ANOTHER company must not become the account owner of this edge.
    foreign_member = CompanyMember.objects.get(user=scene["other_seller"])
    resp = api.patch(f"/api/v1/crm/relationships/{edge.id}/", {"owner_member": foreign_member.id}, format="json")
    assert resp.status_code == 400
    # An outsider can't even see the edge.
    resp = _api(scene["other_seller"], ctx="SELLER").get(f"/api/v1/crm/relationships/{edge.id}/")
    assert resp.status_code == 404


# ── contacts API ────────────────────────────────────────────────────────────


def test_contact_create_and_book_scoping(scene):
    api = _api(scene["seller"], ctx="SELLER")
    resp = api.post(
        "/api/v1/accounts/contacts/",
        {"company_name": "Offline LLC", "contact_name": "Пётр", "email": "p@offline.test"},
        format="json",
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["company_name"] == "Offline LLC" and body["is_primary"] is True
    assert body["company_is_registered"] is False

    rows = api.get("/api/v1/accounts/contacts/").json()
    rows = rows["results"] if isinstance(rows, dict) else rows
    assert len(rows) == 1

    # Another seller's book is empty — contacts never leak across tenants.
    other_rows = _api(scene["other_seller"], ctx="SELLER").get("/api/v1/accounts/contacts/").json()
    other_rows = other_rows["results"] if isinstance(other_rows, dict) else other_rows
    assert other_rows == []


def test_contact_create_maps_service_errors(scene):
    api = _api(scene["seller"], ctx="SELLER")
    resp = api.post(
        "/api/v1/accounts/contacts/",
        {"company_name": "NoReach LLC", "contact_name": "Без Контактов"},
        format="json",
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "CONTACT_NEEDS_EMAIL_OR_PHONE"
