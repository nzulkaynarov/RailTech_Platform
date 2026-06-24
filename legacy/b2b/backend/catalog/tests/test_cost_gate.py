"""Regression: supplier cost (offers / base_price) must NOT leak to buyers (C1),
and the owning seller can edit their own product (H1)."""

import pytest
from decimal import Decimal
from rest_framework.test import APIClient

from accounts.models import Company, CompanyMember, CompanyType, CustomUser, WorkspaceRole
from catalog.models import Product, ProductStatus, SupplierOffer
from master_data.models import Currency


@pytest.fixture
def owned_product(db):
    CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 10})
    CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Client", "sort_order": 10})
    owner_role = WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})[0]
    usd = Currency.objects.get_or_create(code="USD", defaults={"name": "USD", "symbol": "$"})[0]

    seller_co = Company.objects.create(name="Seller Co", inn="7000000001")
    seller_co.types.add(CompanyType.objects.get(code="SUPPLIER"))
    seller = CustomUser.objects.create_user(email="cs@s.test", username="cs@s.test", password="pw", is_active=True)
    CompanyMember.objects.create(user=seller, company=seller_co, role=owner_role, is_active=True, can_sell=True)

    buyer = CustomUser.objects.create_user(email="cb@b.test", username="cb@b.test", password="pw", is_active=True)

    pub = ProductStatus.objects.get_or_create(code="PUBLISHED", defaults={"name": "Published", "sort_order": 10})[0]
    product = Product.objects.create(name="Тестовая деталь", owner_company=seller_co, status=pub)
    SupplierOffer.objects.create(product=product, supplier=seller_co, base_price=Decimal("123.45"), currency=usd)
    return product, seller, buyer


@pytest.mark.django_db
def test_buyer_cannot_see_cost(owned_product):
    product, _seller, buyer = owned_product
    c = APIClient(); c.force_authenticate(buyer)
    data = c.get(f"/api/v1/catalog/products/{product.id}/", SERVER_NAME="localhost").json()
    assert "offers" not in data
    assert "base_price" not in data


@pytest.mark.django_db
def test_owner_seller_sees_cost(owned_product):
    product, seller, _buyer = owned_product
    c = APIClient(); c.force_authenticate(seller)
    data = c.get(f"/api/v1/catalog/products/{product.id}/", SERVER_NAME="localhost").json()
    assert "offers" in data and "base_price" in data


@pytest.mark.django_db
def test_owner_can_edit_buyer_cannot(owned_product):
    product, seller, buyer = owned_product
    cs = APIClient(); cs.force_authenticate(seller)
    assert cs.patch(f"/api/v1/catalog/products/{product.id}/", {"description": "x"}, format="json", SERVER_NAME="localhost").status_code == 200
    cb = APIClient(); cb.force_authenticate(buyer)
    assert cb.patch(f"/api/v1/catalog/products/{product.id}/", {"description": "hax"}, format="json", SERVER_NAME="localhost").status_code == 403
