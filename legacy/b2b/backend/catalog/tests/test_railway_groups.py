"""H5/H6 — RAILWAY_MACHINERY products must carry ≥1 equipment group, enforced at
the API layer with a clean HTTP 400 (never a silently-invalid card, never a 500).

- H5: creating a RAILWAY_MACHINERY product with no equipment_groups → 400.
- H6: removing the last equipment group from a RAILWAY_MACHINERY product → 400
  (the m2m_changed signal raises a DRF ValidationError, not a Django one).
"""

import pytest
from rest_framework.test import APIClient

from accounts.models import Company, CompanyMember, CompanyType, CustomUser, WorkspaceRole
from catalog.models import DomainType, EquipmentGroup, Product, ProductStatus


@pytest.fixture
def railway_setup(db):
    CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 10})
    owner_role = WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})[0]
    domain = DomainType.objects.get_or_create(
        code="RAILWAY_MACHINERY", defaults={"name": "Railway", "sku_prefix": "RW", "sort_order": 10}
    )[0]
    ProductStatus.objects.get_or_create(code="DRAFT", defaults={"name": "Draft", "sort_order": 10})
    group = EquipmentGroup.objects.create(name="Локомотивы")

    seller_co = Company.objects.create(name="Seller Co", inn="7100000001")
    seller_co.types.add(CompanyType.objects.get(code="SUPPLIER"))
    seller = CustomUser.objects.create_user(email="rw@s.test", username="rw@s.test", password="pw", is_active=True)
    CompanyMember.objects.create(user=seller, company=seller_co, role=owner_role, is_active=True, can_sell=True)
    return domain, group, seller, seller_co


@pytest.mark.django_db
def test_create_railway_without_groups_returns_400(railway_setup):
    """H5: API create for RAILWAY_MACHINERY without equipment_groups → 400, not a saved card."""
    domain, _group, seller, _co = railway_setup
    client = APIClient()
    client.force_authenticate(seller)
    resp = client.post(
        "/api/v1/catalog/products/",
        {"name": "Тележка", "domain_type": domain.id},
        format="json",
        SERVER_NAME="localhost",
    )
    assert resp.status_code == 400, resp.content
    assert "equipment_groups" in resp.json()
    assert not Product.objects.filter(name="Тележка").exists()


@pytest.mark.django_db
def test_create_railway_with_group_succeeds(railway_setup):
    """A RAILWAY_MACHINERY product WITH a group is accepted."""
    domain, group, seller, _co = railway_setup
    client = APIClient()
    client.force_authenticate(seller)
    resp = client.post(
        "/api/v1/catalog/products/",
        {"name": "Тележка", "domain_type": domain.id, "equipment_groups": [group.id]},
        format="json",
        SERVER_NAME="localhost",
    )
    assert resp.status_code == 201, resp.content


@pytest.mark.django_db
def test_remove_last_group_returns_400_not_500(railway_setup):
    """H6: clearing the last equipment group → clean 400 (DRF), never an unhandled 500."""
    domain, group, seller, seller_co = railway_setup
    product = Product.objects.create(
        name="Тележка",
        domain_type=domain,
        owner_company=seller_co,
        status=ProductStatus.objects.get(code="DRAFT"),
    )
    product.equipment_groups.add(group)

    client = APIClient()
    client.force_authenticate(seller)
    resp = client.patch(
        f"/api/v1/catalog/products/{product.id}/",
        {"equipment_groups": []},
        format="json",
        SERVER_NAME="localhost",
    )
    assert resp.status_code == 400, resp.content
