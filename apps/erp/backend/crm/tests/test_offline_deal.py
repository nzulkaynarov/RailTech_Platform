"""CB: back-office staff open a Deal for an offline client from the own company's book (contact_id)."""

import pytest
from rest_framework.test import APIClient

from accounts.models import Company, CompanyMember, CompanyType, CustomUser, WorkspaceRole
from accounts.services import create_offline_client
from accounts.services.roles import ensure_default_company_roles
from crm.models import Deal, DealStage


def _seller(email, inn):
    supplier = CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 10})[0]
    CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Client", "sort_order": 10})
    owner = WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})[0]
    co = Company.objects.create(name=f"Seller {email}", inn=inn)
    co.types.add(supplier)
    u = CustomUser.objects.create_user(email=email, username=email, password="pw", is_active=True)
    CompanyMember.objects.create(
        user=u,
        company=co,
        role=owner,
        is_active=True,
        can_sell=True,
        is_primary=True,
        company_roles=[ensure_default_company_roles(co)["CALCULATION"]],
    )
    return u


@pytest.fixture
def seller_with_client(db):
    DealStage.objects.get_or_create(code="DRAFT", defaults={"name": "Черновик", "sort_order": 10})
    seller = _seller("rep@s.test", "700000001")
    result, _ = create_offline_client(
        seller=seller, company_name="Offline Buyer", contact_name="Ivan", email="ivan@b.test", inn="305111222"
    )
    return seller, result["company"], result["contact"]


@pytest.mark.django_db
def test_seller_opens_deal_for_offline_client(seller_with_client):
    seller, company, contact = seller_with_client
    c = APIClient()
    c.force_authenticate(seller)
    resp = c.post("/api/v1/crm/deals/", {"contact_id": contact.id, "title": "Offline RFQ"}, format="json")
    assert resp.status_code == 201, resp.content
    deal = Deal.objects.get(pk=resp.json()["id"])
    assert deal.company_id == company.id  # the client's company, not the seller's
    assert deal.contact_id == contact.id
    assert deal.client_id is None  # no platform user — it's offline


@pytest.mark.django_db
def test_teammate_opens_deal_for_the_teams_contact(seller_with_client):
    """The client book belongs to the own company — a colleague works the same contact."""
    seller, company, contact = seller_with_client
    own = seller.memberships.get().company
    teammate = CustomUser.objects.create_user(email="mate@s.test", username="mate@s.test", password="pw")
    CompanyMember.objects.create(
        user=teammate,
        company=own,
        role=WorkspaceRole.objects.get(code="OWNER"),
        is_active=True,
        can_sell=True,
        company_roles=[ensure_default_company_roles(own)["CALCULATION"]],
    )
    c = APIClient()
    c.force_authenticate(teammate)
    resp = c.post("/api/v1/crm/deals/", {"contact_id": contact.id, "title": "x"}, format="json")
    assert resp.status_code == 201, resp.content
    assert Deal.objects.get(pk=resp.json()["id"]).company_id == company.id


@pytest.mark.django_db
def test_outsider_cannot_open_deal_for_the_teams_contact(seller_with_client):
    """A member of another company (not own-company staff) has an empty book."""
    _, _, contact = seller_with_client
    other_co = Company.objects.create(name="Other Client", inn="700000002")
    other_co.types.add(CompanyType.objects.get(code="CLIENT"))
    other = CustomUser.objects.create_user(email="rep@other.test", username="rep@other.test", password="pw")
    CompanyMember.objects.create(
        user=other, company=other_co, role=WorkspaceRole.objects.get(code="OWNER"), is_active=True, can_sell=True
    )
    c = APIClient()
    c.force_authenticate(other)
    resp = c.post("/api/v1/crm/deals/", {"contact_id": contact.id, "title": "x"}, format="json")
    assert resp.status_code == 403  # contact not in this user's book
