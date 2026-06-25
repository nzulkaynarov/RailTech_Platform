"""Multi-seller RFQ routing — the confidentiality keystone.

A seller may see a buyer's заявка (Deal) ONLY when it is routed to one of their
seller companies (DealSellerRouting) or offers one of their catalog products.
This closes the old see-all leak where seller A could read seller B's buyers' RFQs.
"""

from decimal import Decimal

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import Company, CompanyMember, CompanyType, CustomUser, WorkspaceRole
from catalog.models import Product, ProductStatus
from crm.models import Deal, DealSellerRouting, DealStage, Quote, QuoteItem, QuoteStatus
from crm.services.quotes import route_deal_from_catalog
from master_data.models import Currency


@pytest.fixture
def lookups(db):
    WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})
    CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Client", "sort_order": 10})
    CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 20})
    for code in ("DRAFT", "RFQ_OPEN", "CALCULATING"):
        DealStage.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    QuoteStatus.objects.get_or_create(code="DRAFT", defaults={"name": "Draft", "sort_order": 10})
    ProductStatus.objects.get_or_create(code="PUBLISHED", defaults={"name": "Published", "sort_order": 10})
    Currency.objects.get_or_create(code="USD", defaults={"name": "USD", "symbol": "$"})


def _seller(name, inn, email):
    company = Company.objects.create(name=name, inn=inn)
    company.types.add(CompanyType.objects.get(code="SUPPLIER"))
    user = CustomUser.objects.create_user(email=email, username=email, password="x")
    CompanyMember.objects.create(
        user=user, company=company, role=WorkspaceRole.objects.get(code="OWNER"),
        is_active=True, is_primary=True, can_sell=True,
    )
    return user, company


def _buyer(name, inn, email, buyer_co):
    user = CustomUser.objects.create_user(email=email, username=email, password="x")
    CompanyMember.objects.create(
        user=user, company=buyer_co, role=WorkspaceRole.objects.get(code="OWNER"),
        is_active=True, is_primary=True, can_buy=True,
    )
    return user


def _api(user, ctx="SELLER"):
    client = APIClient()
    client.credentials(
        HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}",
        HTTP_X_ACTIVE_CONTEXT=ctx,
    )
    return client


def _ids(resp):
    data = resp.json()
    rows = data["results"] if isinstance(data, dict) and "results" in data else data
    return {row["id"] for row in rows}


@pytest.fixture
def world(lookups):
    sa_user, sa_co = _seller("Seller A", "A100", "sa@t.test")
    sb_user, sb_co = _seller("Seller B", "B100", "sb@t.test")
    buyer_co = Company.objects.create(name="Buyer Co", inn="C100")
    buyer_co.types.add(CompanyType.objects.get(code="CLIENT"))
    return dict(sa_user=sa_user, sa_co=sa_co, sb_user=sb_user, sb_co=sb_co, buyer_co=buyer_co)


@pytest.mark.django_db
def test_seller_a_cannot_see_seller_b_routed_deal(world):
    draft = DealStage.objects.get(code="DRAFT")
    deal_b = Deal.objects.create(title="B's RFQ", company=world["buyer_co"], stage=draft)
    DealSellerRouting.objects.create(deal=deal_b, seller_company=world["sb_co"])

    # Seller A: not in the list, and cannot retrieve it.
    assert deal_b.id not in _ids(_api(world["sa_user"]).get("/api/v1/crm/deals/"))
    assert _api(world["sa_user"]).get(f"/api/v1/crm/deals/{deal_b.id}/").status_code in (403, 404)

    # Seller B (routed): sees it in the list and can retrieve it.
    assert deal_b.id in _ids(_api(world["sb_user"]).get("/api/v1/crm/deals/"))
    assert _api(world["sb_user"]).get(f"/api/v1/crm/deals/{deal_b.id}/").status_code == 200


@pytest.mark.django_db
def test_seller_a_cannot_see_seller_b_quote(world):
    draft_stage = DealStage.objects.get(code="DRAFT")
    deal_b = Deal.objects.create(title="B's RFQ", company=world["buyer_co"], stage=draft_stage)
    DealSellerRouting.objects.create(deal=deal_b, seller_company=world["sb_co"])
    quote_b = Quote.objects.create(
        deal=deal_b, version=1, status=QuoteStatus.objects.get(code="DRAFT"),
        vat_rate=Decimal("12"), subtotal_excl_vat=Decimal("0"),
        vat_amount=Decimal("0"), total_incl_vat=Decimal("0"),
    )
    # Seller A's quote list must not leak B's quote; retrieve denied too.
    assert quote_b.id not in _ids(_api(world["sa_user"]).get("/api/v1/crm/quotes/"))
    assert _api(world["sa_user"]).get(f"/api/v1/crm/quotes/{quote_b.id}/").status_code in (403, 404)
    assert quote_b.id in _ids(_api(world["sb_user"]).get("/api/v1/crm/quotes/"))


@pytest.mark.django_db
def test_routing_inferred_from_catalog(world):
    draft_stage = DealStage.objects.get(code="DRAFT")
    deal = Deal.objects.create(title="cart RFQ", company=world["buyer_co"], stage=draft_stage)
    quote = Quote.objects.create(
        deal=deal, version=1, status=QuoteStatus.objects.get(code="DRAFT"),
        vat_rate=Decimal("12"), subtotal_excl_vat=Decimal("0"),
        vat_amount=Decimal("0"), total_incl_vat=Decimal("0"),
    )
    product = Product.objects.create(
        name="A's part", owner_company=world["sa_co"], status=ProductStatus.objects.get(code="PUBLISHED")
    )
    QuoteItem.objects.create(
        quote=quote, product=product, quantity=1,
        frozen_base_price=Decimal("100"), frozen_currency=Currency.objects.get(code="USD"),
        margin_percent=Decimal("10"), final_price_excl_vat=Decimal("0"),
    )

    seller_ids = route_deal_from_catalog(deal)

    assert world["sa_co"].id in seller_ids
    assert DealSellerRouting.objects.filter(deal=deal, seller_company=world["sa_co"]).exists()
    assert not DealSellerRouting.objects.filter(deal=deal, seller_company=world["sb_co"]).exists()
    # And it makes the deal visible to seller A only.
    assert deal.id in _ids(_api(world["sa_user"]).get("/api/v1/crm/deals/"))
    assert deal.id not in _ids(_api(world["sb_user"]).get("/api/v1/crm/deals/"))


@pytest.mark.django_db
def test_buyer_routes_free_text_deal_to_seller(world):
    """A buyer routes a free-text заявка → DealSellerRouting rows created, the deal
    becomes visible to the routed seller, and target_sellers_data is exposed."""
    draft = DealStage.objects.get(code="DRAFT")
    deal = Deal.objects.create(title="Free-text RFQ", company=world["buyer_co"], stage=draft)
    buyer = _buyer("Buyer User", "C100", "buyer@t.test", world["buyer_co"])

    resp = _api(buyer, ctx="BUYER").post(
        f"/api/v1/crm/deals/{deal.id}/route/",
        {"seller_company_ids": [world["sb_co"].id]},
        format="json",
    )
    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert {row["id"] for row in body["target_sellers_data"]} == {world["sb_co"].id}

    assert DealSellerRouting.objects.filter(deal=deal, seller_company=world["sb_co"]).exists()
    # Routed seller now sees it; the non-routed seller still does not.
    assert deal.id in _ids(_api(world["sb_user"]).get("/api/v1/crm/deals/"))
    assert deal.id not in _ids(_api(world["sa_user"]).get("/api/v1/crm/deals/"))


@pytest.mark.django_db
def test_non_buyer_cannot_route(world):
    """A seller (non-buyer of the deal's company) is refused routing."""
    draft = DealStage.objects.get(code="DRAFT")
    deal = Deal.objects.create(title="Free-text RFQ", company=world["buyer_co"], stage=draft)

    resp = _api(world["sa_user"], ctx="SELLER").post(
        f"/api/v1/crm/deals/{deal.id}/route/",
        {"seller_company_ids": [world["sb_co"].id]},
        format="json",
    )
    # Seller A is not a member of the buyer company → cannot even reach the object.
    assert resp.status_code in (403, 404)
    assert not DealSellerRouting.objects.filter(deal=deal).exists()


@pytest.mark.django_db
def test_route_rejects_non_seller_company(world):
    """Routing to a non-SUPPLIER company id is rejected with NOT_A_SELLER_COMPANY."""
    draft = DealStage.objects.get(code="DRAFT")
    deal = Deal.objects.create(title="Free-text RFQ", company=world["buyer_co"], stage=draft)
    buyer = _buyer("Buyer User", "C100", "buyer@t.test", world["buyer_co"])

    resp = _api(buyer, ctx="BUYER").post(
        f"/api/v1/crm/deals/{deal.id}/route/",
        {"seller_company_ids": [world["buyer_co"].id]},  # CLIENT, not SUPPLIER
        format="json",
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "NOT_A_SELLER_COMPANY"


@pytest.mark.django_db
def test_suppliers_picker_lists_active_sellers(world):
    """The buyer's picker returns active SUPPLIER companies as {id, name}."""
    buyer = _buyer("Buyer User", "C100", "buyer@t.test", world["buyer_co"])
    resp = _api(buyer, ctx="BUYER").get("/api/v1/crm/deals/suppliers/")
    assert resp.status_code == 200
    rows = resp.json()
    ids = {row["id"] for row in rows}
    assert world["sa_co"].id in ids and world["sb_co"].id in ids
    assert world["buyer_co"].id not in ids
    assert all(set(row.keys()) == {"id", "name"} for row in rows)
