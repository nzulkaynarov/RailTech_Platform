"""Dashboard analytics must be routing-aware (audit #7).

A pure seller is NOT a member of the buyer's deal.company, so scoping the
dashboard by buyer-company id returned ZERO KPIs. The dashboard must instead
scope a context-acting seller by their ROUTED deal ids (DealSellerRouting):
routed deals count toward volume, an unrouted competitor's deal does NOT.
"""

from decimal import Decimal

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import Company, CompanyMember, CompanyType, CustomUser, WorkspaceRole
from crm.models import Deal, DealSellerRouting, DealStage, Quote, QuoteStatus


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


def _api(user, ctx="SELLER"):
    client = APIClient()
    client.credentials(
        HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}",
        HTTP_X_ACTIVE_CONTEXT=ctx,
    )
    return client


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
def test_routed_seller_dashboard_counts_only_routed_deals(lookups):
    """A routed seller's dashboard reports non-zero volume for deals routed to them,
    and does NOT count an unrouted competitor's deal."""
    seller_a, co_a = _seller("Seller A", "A100", "sa@t.test")
    _seller_b, co_b = _seller("Seller B", "B100", "sb@t.test")
    buyer_co = Company.objects.create(name="Buyer Co", inn="C100")
    buyer_co.types.add(CompanyType.objects.get(code="CLIENT"))

    # Routed to A → must count.
    routed = _deal_with_quote(buyer_co, "A's RFQ", Decimal("1000"))
    DealSellerRouting.objects.create(deal=routed, seller_company=co_a)

    # Routed to B only → competitor's deal, must NOT count for A.
    competitor = _deal_with_quote(buyer_co, "B's RFQ", Decimal("5000"))
    DealSellerRouting.objects.create(deal=competitor, seller_company=co_b)

    resp = _api(seller_a).get("/api/v1/crm/analytics/dashboard/?period=90d")
    assert resp.status_code == 200, resp.content
    body = resp.json()

    # A sees its routed deal's volume but not the competitor's larger one.
    assert body["deals_volume"] == 1000.0, body
    assert body["active_requests"] == 1, body


@pytest.mark.django_db
def test_pure_seller_with_no_routing_sees_zero_not_error(lookups):
    """A seller with no routed deals gets zeroes (empty scope), not a 500 and not
    a leak of other buyers' volume."""
    seller_a, _co_a = _seller("Seller A", "A100", "sa@t.test")
    buyer_co = Company.objects.create(name="Buyer Co", inn="C100")
    buyer_co.types.add(CompanyType.objects.get(code="CLIENT"))
    _deal_with_quote(buyer_co, "Some RFQ", Decimal("9999"))  # routed to nobody

    resp = _api(seller_a).get("/api/v1/crm/analytics/dashboard/?period=90d")
    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body["deals_volume"] == 0.0, body
    assert body["active_requests"] == 0, body


@pytest.mark.django_db
def test_catalog_and_clients_kpis_are_tenant_scoped(lookups):
    """E4/F4: catalog_items counts only the seller's OWN active offers ("Active listings" —
    SupplierOffer where the seller is the supplier and is_active=True), NOT the shared PIM, a
    deactivated offer, or a competitor's offers. clients_count counts only the distinct buyers on
    deals routed to the seller — not every CLIENT company on the platform."""
    from catalog.models import SupplierOffer

    seller_a, co_a = _seller("Seller A", "A100", "sa@t.test")
    _seller_b, co_b = _seller("Seller B", "B100", "sb@t.test")
    buyer_co = Company.objects.create(name="Buyer Co", inn="C100")
    buyer_co.types.add(CompanyType.objects.get(code="CLIENT"))
    # A second, unrelated buyer that A never deals with — must NOT inflate A's clients_count.
    other_buyer = Company.objects.create(name="Other Buyer", inn="C200")
    other_buyer.types.add(CompanyType.objects.get(code="CLIENT"))

    # A's catalog = its own ACTIVE offers. One active + one deactivated (excluded); the
    # competitor's active offer must not leak into A's count. (A SupplierOffer is unique per
    # (product, supplier), so the deactivated offer hangs on a second product.)
    product_a = _published_product(co_a, "A-rail-clamp")
    product_a_old = _published_product(co_a, "A-retired-part")
    product_b = _published_product(co_b, "B-competitor-part")
    SupplierOffer.objects.create(product=product_a, supplier=co_a, is_active=True)
    SupplierOffer.objects.create(product=product_a_old, supplier=co_a, is_active=False)
    SupplierOffer.objects.create(product=product_b, supplier=co_b, is_active=True)

    routed = _deal_with_quote(buyer_co, "A's RFQ", Decimal("1000"))
    DealSellerRouting.objects.create(deal=routed, seller_company=co_a)

    body = _api(seller_a).get("/api/v1/crm/analytics/dashboard/?period=90d").json()
    assert body["catalog_items"] == 1, body  # only A's own ACTIVE offer
    assert body["clients_count"] == 1, body  # only the one routed buyer, not all CLIENTs
