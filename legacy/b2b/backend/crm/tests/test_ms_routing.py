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
from crm.services.rfq import route_deal_from_catalog
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
        user=user,
        company=company,
        role=WorkspaceRole.objects.get(code="OWNER"),
        is_active=True,
        is_primary=True,
        can_sell=True,
    )
    return user, company


def _buyer(name, inn, email, buyer_co):
    user = CustomUser.objects.create_user(email=email, username=email, password="x")
    CompanyMember.objects.create(
        user=user,
        company=buyer_co,
        role=WorkspaceRole.objects.get(code="OWNER"),
        is_active=True,
        is_primary=True,
        can_buy=True,
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
        deal=deal_b,
        version=1,
        status=QuoteStatus.objects.get(code="DRAFT"),
        vat_rate=Decimal("12"),
        subtotal_excl_vat=Decimal("0"),
        vat_amount=Decimal("0"),
        total_incl_vat=Decimal("0"),
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
        deal=deal,
        version=1,
        status=QuoteStatus.objects.get(code="DRAFT"),
        vat_rate=Decimal("12"),
        subtotal_excl_vat=Decimal("0"),
        vat_amount=Decimal("0"),
        total_incl_vat=Decimal("0"),
    )
    product = Product.objects.create(
        name="A's part", owner_company=world["sa_co"], status=ProductStatus.objects.get(code="PUBLISHED")
    )
    QuoteItem.objects.create(
        quote=quote,
        product=product,
        quantity=1,
        frozen_base_price=Decimal("100"),
        frozen_currency=Currency.objects.get(code="USD"),
        margin_percent=Decimal("10"),
        final_price_excl_vat=Decimal("0"),
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


@pytest.mark.django_db
def test_seller_cannot_see_deal_offering_their_product_routed_elsewhere(world):
    """Regression (review 2026-06-25 #2): a deal routed to seller B that merely references
    seller A's catalog product must NOT be visible to seller A — routing rows are the only grant."""
    draft = DealStage.objects.get(code="DRAFT")
    deal_b = Deal.objects.create(title="B deal", company=world["buyer_co"], stage=draft)
    DealSellerRouting.objects.create(deal=deal_b, seller_company=world["sb_co"])
    quote = Quote.objects.create(
        deal=deal_b,
        version=1,
        status=QuoteStatus.objects.get(code="DRAFT"),
        vat_rate=Decimal("12"),
        subtotal_excl_vat=Decimal("0"),
        vat_amount=Decimal("0"),
        total_incl_vat=Decimal("0"),
    )
    a_product = Product.objects.create(
        name="A part", owner_company=world["sa_co"], status=ProductStatus.objects.get(code="PUBLISHED")
    )
    QuoteItem.objects.create(quote=quote, product=a_product, quantity=1, final_price_excl_vat=Decimal("0"))
    assert deal_b.id not in _ids(_api(world["sa_user"]).get("/api/v1/crm/deals/"))
    assert _api(world["sa_user"]).get(f"/api/v1/crm/deals/{deal_b.id}/").status_code in (403, 404)


@pytest.mark.django_db
def test_seller_cannot_write_item_to_unrouted_quote(world):
    """Regression (review 2026-06-25 #1): seller A cannot POST a quote item onto a quote whose
    deal is routed to seller B (no write-tamper on a competitor's КП)."""
    draft = DealStage.objects.get(code="DRAFT")
    deal_b = Deal.objects.create(title="B deal", company=world["buyer_co"], stage=draft)
    DealSellerRouting.objects.create(deal=deal_b, seller_company=world["sb_co"])
    quote = Quote.objects.create(
        deal=deal_b,
        version=1,
        status=QuoteStatus.objects.get(code="DRAFT"),
        vat_rate=Decimal("12"),
        subtotal_excl_vat=Decimal("0"),
        vat_amount=Decimal("0"),
        total_incl_vat=Decimal("0"),
    )
    a_product = Product.objects.create(
        name="A part", owner_company=world["sa_co"], status=ProductStatus.objects.get(code="PUBLISHED")
    )
    resp = _api(world["sa_user"]).post(
        "/api/v1/crm/quote-items/", {"quote": quote.id, "product": a_product.id, "quantity": 1}, format="json"
    )
    assert resp.status_code == 403


@pytest.mark.django_db
def test_seller_a_cannot_see_seller_b_quote_costs_on_corouted_deal(world):
    """Audit C1: on a deal routed to BOTH A and B, seller A must not read seller B's quote
    cost/margin fields. B prepares the quote (prepared_by a B member, margin set)."""
    draft = DealStage.objects.get(code="DRAFT")
    deal = Deal.objects.create(title="co-routed", company=world["buyer_co"], stage=draft)
    DealSellerRouting.objects.create(deal=deal, seller_company=world["sa_co"])
    DealSellerRouting.objects.create(deal=deal, seller_company=world["sb_co"])
    b_quote = Quote.objects.create(
        deal=deal,
        version=1,
        status=QuoteStatus.objects.get(code="DRAFT"),
        prepared_by=world["sb_user"],
        vat_rate=Decimal("12"),
        subtotal_excl_vat=Decimal("0"),
        vat_amount=Decimal("0"),
        total_incl_vat=Decimal("0"),
    )
    QuoteItem.objects.create(
        quote=b_quote,
        imported_raw_name="part",
        quantity=1,
        frozen_base_price=Decimal("100"),
        margin_percent=Decimal("30"),
        final_price_excl_vat=Decimal("130"),
    )
    resp = _api(world["sa_user"]).get(f"/api/v1/crm/quote-items/?quote__deal_id={deal.id}")
    assert resp.status_code == 200
    rows = resp.json().get("results", resp.json())
    for row in rows:
        assert "margin_percent" not in row, "C1 leak: B's margin visible to A"
        assert "frozen_base_price" not in row, "C1 leak: B's cost visible to A"


@pytest.mark.django_db
def test_routed_seller_can_price_buyer_prepared_quote(world):
    """Regression (prod $224-instead-of-$68k bug): the buyer's request lines and the seller's
    КП are the SAME quote, created by the BUYER (prepared_by=buyer). Scoping КП items by
    prepared_by's *seller* company wrongly hid the seller's own quote → item PATCH 404 →
    prices never saved → subtotal stuck at 0. The routed seller must be able to price it;
    a competing seller still must not (audit H1)."""
    draft_stage = DealStage.objects.get(code="DRAFT")
    deal = Deal.objects.create(title="Buyer RFQ", company=world["buyer_co"], stage=draft_stage)
    DealSellerRouting.objects.create(deal=deal, seller_company=world["sb_co"])  # routed to Seller B
    buyer_user = _buyer("Buyer U", "C100", "buyeru@t.test", world["buyer_co"])
    quote = Quote.objects.create(
        deal=deal,
        version=1,
        status=QuoteStatus.objects.get(code="DRAFT"),
        prepared_by=buyer_user,
        vat_rate=Decimal("12"),
        subtotal_excl_vat=Decimal("0"),
        vat_amount=Decimal("0"),
        total_incl_vat=Decimal("0"),
    )
    item = QuoteItem.objects.create(quote=quote, imported_raw_name="Рельс Р65", quantity=10)

    # Routed seller B prices the buyer-prepared line → 200, subtotal recalculated (was 404 → 0).
    resp = _api(world["sb_user"]).patch(
        f"/api/v1/crm/quote-items/{item.id}/",
        {"frozen_base_price": "500", "margin_percent": "20", "quantity": "10"},
        format="json",
    )
    assert resp.status_code == 200, resp.content
    quote.refresh_from_db()
    assert quote.subtotal_excl_vat > 0

    # Competing seller A (not routed) still cannot touch it — H1 preserved.
    blocked = _api(world["sa_user"]).patch(
        f"/api/v1/crm/quote-items/{item.id}/",
        {"frozen_base_price": "1"},
        format="json",
    )
    assert blocked.status_code in (403, 404)


@pytest.mark.django_db
def test_dual_membership_preparer_own_kp_stays_visible(world):
    """Dual-membership read-scope edge: a КП prepared by a user who is a member of BOTH
    seller A AND a competing seller B must STILL be visible to a PURE seller-A viewer when
    acting for A. Without subtracting the viewer's own-company members from the competing-
    preparer exclusion set, the dual preparer (via their B membership) lands in
    competing_preparer_ids → A's own legitimately-prepared КП gets hidden from A's viewers.
    A purely-B preparer's КП still stays hidden (no cross-seller leak)."""
    draft = DealStage.objects.get(code="DRAFT")
    deal = Deal.objects.create(title="co-routed", company=world["buyer_co"], stage=draft)
    DealSellerRouting.objects.create(deal=deal, seller_company=world["sa_co"])
    DealSellerRouting.objects.create(deal=deal, seller_company=world["sb_co"])

    # `dual_preparer` belongs to BOTH seller A (their own company) and competing seller B.
    dual_preparer = CustomUser.objects.create_user(email="dualprep@t.test", username="dualprep@t.test", password="x")
    CompanyMember.objects.create(
        user=dual_preparer,
        company=world["sa_co"],
        role=WorkspaceRole.objects.get(code="OWNER"),
        is_active=True,
        is_primary=True,
        can_sell=True,
    )
    CompanyMember.objects.create(
        user=dual_preparer,
        company=world["sb_co"],
        role=WorkspaceRole.objects.get(code="OWNER"),
        is_active=True,
        is_primary=False,
        can_sell=True,
    )

    # A's own КП, prepared by the dual member acting for A.
    a_quote = Quote.objects.create(
        deal=deal,
        version=1,
        status=QuoteStatus.objects.get(code="DRAFT"),
        prepared_by=dual_preparer,
        vat_rate=Decimal("12"),
        subtotal_excl_vat=Decimal("0"),
        vat_amount=Decimal("0"),
        total_incl_vat=Decimal("0"),
    )
    a_item = QuoteItem.objects.create(quote=a_quote, imported_raw_name="A part", quantity=1)

    # A purely-competing B preparer's КП — must stay hidden from the pure-A viewer.
    b_quote = Quote.objects.create(
        deal=deal,
        version=2,
        status=QuoteStatus.objects.get(code="DRAFT"),
        prepared_by=world["sb_user"],
        vat_rate=Decimal("12"),
        subtotal_excl_vat=Decimal("0"),
        vat_amount=Decimal("0"),
        total_incl_vat=Decimal("0"),
    )
    b_item = QuoteItem.objects.create(quote=b_quote, imported_raw_name="B part", quantity=1)

    # sa_user is a PURE seller-A member (the viewer).
    visible = _ids(_api(world["sa_user"]).get(f"/api/v1/crm/quote-items/?quote__deal_id={deal.id}"))
    assert a_item.id in visible, "A's own КП (prepared by a dual A+B member) wrongly hidden from A"
    assert b_item.id not in visible, "B's КП leaked to seller A (cross-seller leak)"


@pytest.mark.django_db
def test_quote_items_filter_scopes_to_requested_deal(world):
    """DRF silent-filter contract: GET /crm/quote-items/?quote__deal_id=<dealA> returns ONLY
    deal-A items, never deal-B's. Pins the frontend↔backend filter-key contract so a renamed
    or unknown ?filter= param can't silently fall back to "all rows" (the «Открыть КП → wrong
    deal» bug). Run as a routed seller who can legitimately see both deals."""
    draft = DealStage.objects.get(code="DRAFT")
    deal_a = Deal.objects.create(title="Deal A", company=world["buyer_co"], stage=draft)
    deal_b = Deal.objects.create(title="Deal B", company=world["buyer_co"], stage=draft)
    # Seller B is routed to BOTH deals, so without the filter it would see items from both.
    DealSellerRouting.objects.create(deal=deal_a, seller_company=world["sb_co"])
    DealSellerRouting.objects.create(deal=deal_b, seller_company=world["sb_co"])

    quote_a = Quote.objects.create(
        deal=deal_a,
        version=1,
        status=QuoteStatus.objects.get(code="DRAFT"),
        prepared_by=world["sb_user"],
        vat_rate=Decimal("12"),
        subtotal_excl_vat=Decimal("0"),
        vat_amount=Decimal("0"),
        total_incl_vat=Decimal("0"),
    )
    quote_b = Quote.objects.create(
        deal=deal_b,
        version=1,
        status=QuoteStatus.objects.get(code="DRAFT"),
        prepared_by=world["sb_user"],
        vat_rate=Decimal("12"),
        subtotal_excl_vat=Decimal("0"),
        vat_amount=Decimal("0"),
        total_incl_vat=Decimal("0"),
    )
    item_a = QuoteItem.objects.create(quote=quote_a, imported_raw_name="A line", quantity=1)
    item_b = QuoteItem.objects.create(quote=quote_b, imported_raw_name="B line", quantity=1)

    resp = _api(world["sb_user"]).get(f"/api/v1/crm/quote-items/?quote__deal_id={deal_a.id}")
    assert resp.status_code == 200, resp.content
    ids = _ids(resp)
    assert item_a.id in ids, "deal-A item missing from its own filter result"
    assert item_b.id not in ids, "filter silently leaked deal-B's item (filter-key drift)"


def _quote(deal, seller_user, version, total):
    return Quote.objects.create(
        deal=deal,
        version=version,
        prepared_by=seller_user,
        status=QuoteStatus.objects.get(code="DRAFT"),
        vat_rate=Decimal("12"),
        subtotal_excl_vat=Decimal(str(total)),
        vat_amount=Decimal("0"),
        total_incl_vat=Decimal(str(total)),
    )


@pytest.mark.django_db
def test_deal_nested_quotes_scoped_per_seller(world):
    """SEC audit #2: a deal routed to BOTH sellers A and B, each with its own КП. Seller B's
    GET on the SHARED deal must not surface A's quote via the nested `quotes`/`active_quote`
    (the deal-nested prefetch previously bypassed QuoteViewSet's per-seller filter)."""
    draft = DealStage.objects.get(code="DRAFT")
    deal = Deal.objects.create(title="Shared RFQ", company=world["buyer_co"], stage=draft)
    DealSellerRouting.objects.create(deal=deal, seller_company=world["sa_co"])
    DealSellerRouting.objects.create(deal=deal, seller_company=world["sb_co"])
    quote_a = _quote(deal, world["sa_user"], 1, 111)
    quote_b = _quote(deal, world["sb_user"], 2, 222)  # higher version, but scoped away from A

    body_b = _api(world["sb_user"]).get(f"/api/v1/crm/deals/{deal.id}/").json()
    ids_b = {q["id"] for q in body_b.get("quotes", [])}
    assert quote_a.id not in ids_b, "seller B leaked seller A's quote via the deal detail"
    assert quote_b.id in ids_b
    assert body_b.get("active_quote", {}).get("id") == quote_b.id

    body_a = _api(world["sa_user"]).get(f"/api/v1/crm/deals/{deal.id}/").json()
    ids_a = {q["id"] for q in body_a.get("quotes", [])}
    assert quote_b.id not in ids_a, "seller A leaked seller B's quote via the deal detail"
    assert body_a.get("active_quote", {}).get("id") == quote_a.id


@pytest.mark.django_db
def test_target_sellers_hidden_from_co_routed_seller(world):
    """SEC audit #5: on a deal routed to sellers A and B, seller B's deal view lists only B in
    target_sellers_data (never competitor A); the buyer (RFQ owner) still sees the full roster."""
    draft = DealStage.objects.get(code="DRAFT")
    deal = Deal.objects.create(title="Shared RFQ", company=world["buyer_co"], stage=draft)
    DealSellerRouting.objects.create(deal=deal, seller_company=world["sa_co"])
    DealSellerRouting.objects.create(deal=deal, seller_company=world["sb_co"])

    body_b = _api(world["sb_user"]).get(f"/api/v1/crm/deals/{deal.id}/").json()
    seller_ids_b = {s["id"] for s in body_b.get("target_sellers_data", [])}
    assert seller_ids_b == {world["sb_co"].id}, "seller B saw a competitor in target_sellers_data"

    buyer_user = _buyer("Buyer", "C100b", "buyer@t.test", world["buyer_co"])
    body_buyer = _api(buyer_user, ctx="BUYER").get(f"/api/v1/crm/deals/{deal.id}/").json()
    seller_ids_buyer = {s["id"] for s in body_buyer.get("target_sellers_data", [])}
    assert seller_ids_buyer == {world["sa_co"].id, world["sb_co"].id}, "buyer should see the full roster"


@pytest.mark.django_db
def test_quote_create_blocked_on_unrouted_deal(world):
    """SEC audit #6: a seller with pricing capability cannot POST a КП onto a deal their
    company is not routed to (rogue active_quote / integrity). Only the routed seller can."""
    draft = DealStage.objects.get(code="DRAFT")
    deal = Deal.objects.create(title="B-only RFQ", company=world["buyer_co"], stage=draft)
    DealSellerRouting.objects.create(deal=deal, seller_company=world["sb_co"])  # only B routed

    resp_a = _api(world["sa_user"]).post("/api/v1/crm/quotes/", {"deal": deal.id}, format="json")
    assert resp_a.status_code == 403, resp_a.content
    assert resp_a.json().get("detail") == "NO_ACCESS_TO_DEAL"

    resp_b = _api(world["sb_user"]).post("/api/v1/crm/quotes/", {"deal": deal.id}, format="json")
    assert resp_b.status_code == 201, resp_b.content
