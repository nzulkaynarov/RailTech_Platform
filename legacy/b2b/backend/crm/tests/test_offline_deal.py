"""CB: a seller opens a Deal for an offline client from their own book (contact_id)."""

import pytest
from rest_framework.test import APIClient

from accounts.models import Company, CompanyMember, CompanyType, CustomUser, WorkspaceRole
from accounts.services import create_offline_client
from crm.models import Deal, DealStage


def _seller(email, inn):
    supplier = CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 10})[0]
    CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Client", "sort_order": 10})
    owner = WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})[0]
    co = Company.objects.create(name=f"Seller {email}", inn=inn)
    co.types.add(supplier)
    u = CustomUser.objects.create_user(email=email, username=email, password="pw", is_active=True)
    CompanyMember.objects.create(user=u, company=co, role=owner, is_active=True, can_sell=True, is_primary=True)
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
    c = APIClient(); c.force_authenticate(seller)
    resp = c.post("/api/v1/crm/deals/", {"contact_id": contact.id, "title": "Offline RFQ"}, format="json")
    assert resp.status_code == 201, resp.content
    deal = Deal.objects.get(pk=resp.json()["id"])
    assert deal.company_id == company.id      # the client's company, not the seller's
    assert deal.contact_id == contact.id
    assert deal.client_id is None             # no platform user — it's offline


@pytest.mark.django_db
def test_seller_cannot_open_deal_for_other_sellers_contact(seller_with_client):
    _, _, contact = seller_with_client
    other = _seller("rep@other.test", "700000002")
    c = APIClient(); c.force_authenticate(other)
    resp = c.post("/api/v1/crm/deals/", {"contact_id": contact.id, "title": "x"}, format="json")
    assert resp.status_code == 403  # contact not in this seller's book
