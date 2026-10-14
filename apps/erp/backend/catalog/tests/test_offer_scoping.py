"""C2 — SupplierOffer tenant isolation (a seller sees/edits only its own offers,
can't spoof a competitor's supplier) + M6 — owner_company immutable for non-admins."""

from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from accounts.models import Company, CompanyMember, CompanyType, CustomUser, WorkspaceRole
from catalog.models import Product, ProductStatus, SupplierOffer
from master_data.models import Currency


@pytest.fixture
def two_sellers(db):
    CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 10})
    owner_role = WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})[0]
    usd = Currency.objects.get_or_create(code="USD", defaults={"name": "USD", "symbol": "$"})[0]
    pub = ProductStatus.objects.get_or_create(code="PUBLISHED", defaults={"name": "Published", "sort_order": 10})[0]
    supplier_type = CompanyType.objects.get(code="SUPPLIER")

    def make_seller(name, inn, email):
        company = Company.objects.create(name=name, inn=inn)
        company.types.add(supplier_type)
        user = CustomUser.objects.create_user(email=email, username=email, password="pw", is_active=True)
        CompanyMember.objects.create(user=user, company=company, role=owner_role, is_active=True, can_sell=True)
        return company, user

    co_a, seller_a = make_seller("Seller A", "7000000001", "a@s.test")
    co_b, seller_b = make_seller("Seller B", "7000000002", "b@s.test")

    # Separate products so the (product, supplier) unique constraint doesn't interfere
    # with the reassignment-guard test.
    product = Product.objects.create(name="Деталь A", owner_company=co_a, status=pub)
    product_b = Product.objects.create(name="Деталь B", owner_company=co_b, status=pub)
    offer_a = SupplierOffer.objects.create(product=product, supplier=co_a, base_price=Decimal("100"), currency=usd)
    offer_b = SupplierOffer.objects.create(product=product_b, supplier=co_b, base_price=Decimal("200"), currency=usd)

    buyer = CustomUser.objects.create_user(email="buy@b.test", username="buy@b.test", password="pw", is_active=True)
    admin = CustomUser.objects.create_user(
        email="adm@p.test", username="adm@p.test", password="pw", is_active=True, is_staff=True, is_superuser=True
    )
    return {
        "co_a": co_a,
        "seller_a": seller_a,
        "co_b": co_b,
        "seller_b": seller_b,
        "product": product,
        "offer_a": offer_a,
        "offer_b": offer_b,
        "buyer": buyer,
        "admin": admin,
        "usd": usd,
    }


def _client(user):
    c = APIClient()
    c.force_authenticate(user)
    return c


# ---- C2: read scoping ----


@pytest.mark.django_db
def test_seller_sees_only_own_offers(two_sellers):
    ids = [o["id"] for o in _client(two_sellers["seller_a"]).get("/api/v1/catalog/offers/").json()["results"]]
    assert two_sellers["offer_a"].id in ids
    assert two_sellers["offer_b"].id not in ids


@pytest.mark.django_db
def test_buyer_sees_no_offers(two_sellers):
    assert _client(two_sellers["buyer"]).get("/api/v1/catalog/offers/").json()["count"] == 0


@pytest.mark.django_db
def test_admin_sees_all_offers(two_sellers):
    ids = [o["id"] for o in _client(two_sellers["admin"]).get("/api/v1/catalog/offers/").json()["results"]]
    assert {two_sellers["offer_a"].id, two_sellers["offer_b"].id} <= set(ids)


# ---- C2: write scoping / spoofing ----


@pytest.mark.django_db
def test_seller_creates_offer_for_own_supplier(two_sellers):
    """Seller creates an offer for their own company → allowed."""
    p2 = Product.objects.create(
        name="Деталь 2", owner_company=two_sellers["co_a"], status=two_sellers["product"].status
    )
    resp = _client(two_sellers["seller_a"]).post(
        "/api/v1/catalog/offers/",
        {"product": p2.id, "supplier": two_sellers["co_a"].id, "base_price": "55", "currency": two_sellers["usd"].id},
        format="json",
    )
    assert resp.status_code == 201, resp.content
    assert resp.json()["supplier"] == two_sellers["co_a"].id


@pytest.mark.django_db
def test_seller_cannot_spoof_competitor_supplier_on_create(two_sellers):
    p2 = Product.objects.create(
        name="Деталь 3", owner_company=two_sellers["co_a"], status=two_sellers["product"].status
    )
    resp = _client(two_sellers["seller_a"]).post(
        "/api/v1/catalog/offers/",
        {"product": p2.id, "supplier": two_sellers["co_b"].id, "base_price": "55", "currency": two_sellers["usd"].id},
        format="json",
    )
    assert resp.status_code == 403


@pytest.mark.django_db
def test_seller_cannot_edit_competitor_offer(two_sellers):
    resp = _client(two_sellers["seller_b"]).patch(
        f"/api/v1/catalog/offers/{two_sellers['offer_a'].id}/", {"base_price": "1"}, format="json"
    )
    assert resp.status_code in (403, 404)  # scoped out of queryset → 404, or object perm → 403


@pytest.mark.django_db
def test_seller_cannot_reassign_own_offer_supplier(two_sellers):
    offer_a = two_sellers["offer_a"]
    resp = _client(two_sellers["seller_a"]).patch(
        f"/api/v1/catalog/offers/{offer_a.id}/", {"supplier": two_sellers["co_b"].id}, format="json"
    )
    assert resp.status_code == 200
    offer_a.refresh_from_db()
    assert offer_a.supplier_id == two_sellers["co_a"].id  # pinned, not reassigned


# ---- M6: owner_company immutability ----


@pytest.mark.django_db
def test_seller_cannot_patch_owner_company(two_sellers):
    product = two_sellers["product"]
    resp = _client(two_sellers["seller_a"]).patch(
        f"/api/v1/catalog/products/{product.id}/", {"owner_company": two_sellers["co_b"].id}, format="json"
    )
    assert resp.status_code == 200
    product.refresh_from_db()
    assert product.owner_company_id == two_sellers["co_a"].id  # read-only → unchanged


@pytest.mark.django_db
def test_owner_company_readonly_even_for_admin(two_sellers):
    """owner_company is read-only on the API serializer for everyone — ownership
    reassignment is an engineer action via Django Unfold, not a tenant-facing API op
    (ADR-0002). The PATCH succeeds but the field is ignored."""
    product = two_sellers["product"]
    resp = _client(two_sellers["admin"]).patch(
        f"/api/v1/catalog/products/{product.id}/", {"owner_company": two_sellers["co_b"].id}, format="json"
    )
    assert resp.status_code == 200
    product.refresh_from_db()
    assert product.owner_company_id == two_sellers["co_a"].id
