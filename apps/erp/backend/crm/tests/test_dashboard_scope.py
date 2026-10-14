"""Dashboard analytics scope (audit #7, E4/F4) — single seller (M1-ERP-02 wave 3).

The seller of every deal is the own company: its staff see the whole pipeline; a buyer account
(until M2-ERP-01) sees only its own company's deals. Catalog KPI = the own company's active
offers; clients KPI = distinct client companies that have deals.
"""

from decimal import Decimal

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import Company, CompanyMember, CompanyType, CustomUser, WorkspaceRole
from crm.models import Deal, DealStage, Quote, QuoteStatus


@pytest.fixture
def lookups(db):
    WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})
    CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Client", "sort_order": 10})
    CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 20})
    DealStage.objects.get_or_create(code="DRAFT", defaults={"name": "Draft", "sort_order": 10})
    QuoteStatus.objects.get_or_create(code="DRAFT", defaults={"name": "Draft", "sort_order": 10})
    from catalog.models import ProductStatus

    ProductStatus.objects.get_or_create(code="PUBLISHED", defaults={"name": "Published", "sort_order": 20})


def _published_product(owner_co, name):
    """A PUBLISHED catalog product owned by `owner_co` (a PIM row to hang offers on)."""
    from catalog.models import Product, ProductStatus

    return Product.objects.create(
        name=name,
        sku=name,
        description="",
        manufacturer_part_number="",
        gost_drawing="",
        owner_company=owner_co,
        status=ProductStatus.objects.get(code="PUBLISHED"),
    )


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


def _api(user):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
    return client


def _buyer_company(name, inn):
    company = Company.objects.create(name=name, inn=inn)
    company.types.add(CompanyType.objects.get(code="CLIENT"))
    return company


def _deal_with_quote(buyer_co, title, total):
    """A buyer deal carrying a single quote worth `total` (drives deals_volume)."""
    deal = Deal.objects.create(title=title, company=buyer_co, stage=DealStage.objects.get(code="DRAFT"))
    Quote.objects.create(
        deal=deal,
        version=1,
        status=QuoteStatus.objects.get(code="DRAFT"),
        vat_rate=Decimal("12"),
        subtotal_excl_vat=total,
        vat_amount=Decimal("0"),
        total_incl_vat=total,
    )
    return deal


@pytest.mark.django_db
def test_staff_dashboard_counts_every_deal(lookups):
    """The seller of every deal is the own company: its staff see the whole pipeline's volume."""
    staff, _own = _seller("Own Co", "A100", "sa@t.test")
    buyer_co = _buyer_company("Buyer Co", "C100")
    other_buyer = _buyer_company("Other Buyer", "C200")
    _deal_with_quote(buyer_co, "RFQ 1", Decimal("1000"))
    _deal_with_quote(other_buyer, "RFQ 2", Decimal("5000"))

    resp = _api(staff).get("/api/v1/crm/analytics/dashboard/?period=90d")
    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body["deals_volume"] == 6000.0, body
    assert body["active_requests"] == 2, body


@pytest.mark.django_db
def test_buyer_dashboard_counts_only_own_company(lookups):
    """A buyer account (until M2-ERP-01) sees only its own company's deals — never another
    client's volume."""
    _seller("Own Co", "A100", "sa@t.test")
    buyer_co = _buyer_company("Buyer Co", "C100")
    other_buyer = _buyer_company("Other Buyer", "C200")
    buyer = CustomUser.objects.create_user(email="b@t.test", username="b@t.test", password="x")
    CompanyMember.objects.create(
        user=buyer, company=buyer_co, role=WorkspaceRole.objects.get(code="OWNER"), is_active=True, can_buy=True
    )
    _deal_with_quote(buyer_co, "Mine", Decimal("1000"))
    _deal_with_quote(other_buyer, "Not mine", Decimal("5000"))

    body = _api(buyer).get("/api/v1/crm/analytics/dashboard/?period=90d").json()
    assert body["deals_volume"] == 1000.0, body
    assert body["active_requests"] == 1, body


@pytest.mark.django_db
def test_catalog_and_clients_kpis_for_staff(lookups):
    """E4/F4: catalog_items counts only the own company's ACTIVE offers ("Active listings"), NOT the
    shared PIM, a deactivated offer, or a catalog supplier's offers. clients_count counts the
    distinct client companies that have deals — not every CLIENT company in the database."""
    from catalog.models import SupplierOffer

    staff, own = _seller("Own Co", "A100", "sa@t.test")
    # A catalog supplier: a seller-type company WITHOUT members — a counterparty, not the own company.
    supplier = Company.objects.create(name="Catalog Supplier", inn="B100")
    supplier.types.add(CompanyType.objects.get(code="SUPPLIER"))
    buyer_co = _buyer_company("Buyer Co", "C100")
    _buyer_company("Idle Buyer", "C200")  # no deals — must not inflate clients_count

    product_a = _published_product(own, "A-rail-clamp")
    product_a_old = _published_product(own, "A-retired-part")
    product_b = _published_product(supplier, "B-supplier-part")
    SupplierOffer.objects.create(product=product_a, supplier=own, is_active=True)
    SupplierOffer.objects.create(product=product_a_old, supplier=own, is_active=False)
    SupplierOffer.objects.create(product=product_b, supplier=supplier, is_active=True)

    _deal_with_quote(buyer_co, "RFQ", Decimal("1000"))

    body = _api(staff).get("/api/v1/crm/analytics/dashboard/?period=90d").json()
    assert body["catalog_items"] == 1, body  # only the own company's ACTIVE offer
    assert body["clients_count"] == 1, body  # only the client that has a deal
