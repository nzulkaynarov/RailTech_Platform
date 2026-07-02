"""Tests for pricing-assist (ADR-0006 Move 3) — autofill КП line costs from the seller's SupplierOffer.

Covers the deterministic lookup (own-offer scoping, active/in-date filtering, cheapest pick) and the
quote-level orchestration with its cost-confidentiality gate.
"""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from accounts.models import Company, CompanyMember, CompanyType, CustomUser, VerificationStatus, WorkspaceRole
from catalog.models import Product, SupplierOffer
from crm.models import Deal, DealStage, Quote, QuoteItem, QuoteStatus
from crm.services.pricing_assist import suggest_line_pricing, suggest_pricing_for_products, suggest_quote_pricing
from master_data.models import Currency


@pytest.fixture
def base(db):
    VerificationStatus.objects.get_or_create(code="L2_VERIFIED", defaults={"name": "L2", "sort_order": 30})
    CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 20})
    usd = Currency.objects.get_or_create(code="USD", defaults={"name": "USD", "symbol": "$", "sort_order": 10})[0]
    QuoteStatus.objects.get_or_create(code="DRAFT", defaults={"name": "Draft", "sort_order": 10})
    DealStage.objects.get_or_create(code="RFQ_OPEN", defaults={"name": "RFQ", "sort_order": 10})
    seller_a = Company.objects.create(name="Seller A", inn="2220000001")
    seller_b = Company.objects.create(name="Seller B", inn="2220000002")
    product = Product.objects.create(name="Автосцепка СА-3")
    return locals()


def _offer(product, supplier, price, **kw):
    return SupplierOffer.objects.create(
        product=product,
        supplier=supplier,
        base_price=Decimal(price),
        currency=kw.pop("currency", None),
        is_active=kw.pop("is_active", True),
        **kw,
    )


def test_suggest_line_pricing_returns_sellers_own_offer(base):
    _offer(
        base["product"],
        base["seller_a"],
        "100.00",
        currency=base["usd"],
        in_stock_lead_time_days=7,
        supplier_sku="SKU-A",
    )
    out = suggest_line_pricing(base["product"].id, base["seller_a"].id)
    assert out["base_price"] == "100.00" and out["currency"] == "USD"
    assert out["lead_time_days"] == 7 and out["supplier_sku"] == "SKU-A"


def test_none_when_seller_has_no_offer(base):
    assert suggest_line_pricing(base["product"].id, base["seller_a"].id) is None


def test_scoped_to_own_company_never_competitors_price(base):
    _offer(base["product"], base["seller_b"], "50.00", currency=base["usd"])  # competitor's cheaper offer
    # Seller A has no offer → gets nothing; B's price is never leaked to A.
    assert suggest_line_pricing(base["product"].id, base["seller_a"].id) is None


def test_inactive_offer_excluded(base):
    _offer(base["product"], base["seller_a"], "100.00", currency=base["usd"], is_active=False)
    assert suggest_line_pricing(base["product"].id, base["seller_a"].id) is None


def test_expired_offer_excluded(base):
    expired_product = Product.objects.create(name="Просроченный товар")
    yesterday = timezone.now().date() - timedelta(days=1)
    _offer(expired_product, base["seller_a"], "200.00", currency=base["usd"], valid_until=yesterday)
    assert suggest_line_pricing(expired_product.id, base["seller_a"].id) is None


def test_batch_picks_cheapest_active_offer_per_product(base):
    p2 = Product.objects.create(name="Баббит Б83")
    _offer(base["product"], base["seller_a"], "100.00", currency=base["usd"])
    _offer(p2, base["seller_a"], "30.00", currency=base["usd"])
    out = suggest_pricing_for_products([base["product"].id, p2.id], base["seller_a"].id)
    assert set(out) == {base["product"].id, p2.id}
    assert out[p2.id]["base_price"] == "30.00"


# ─── quote-level orchestration + cost-confidentiality gate ──────────────────


def _quote_with_item(base, product):
    deal = Deal.objects.create(title="RFQ", company=base["seller_b"], stage=DealStage.objects.get(code="RFQ_OPEN"))
    quote = Quote.objects.create(
        deal=deal, version=1, status=QuoteStatus.objects.get(code="DRAFT"), seller_company=base["seller_a"]
    )
    QuoteItem.objects.create(quote=quote, product=product, quantity=1)
    QuoteItem.objects.create(quote=quote, quantity=1, imported_raw_name="free text line")  # unmatched → skipped
    return quote


def test_suggest_quote_pricing_returns_matched_line_suggestions(base):
    _offer(base["product"], base["seller_a"], "100.00", currency=base["usd"], in_stock_lead_time_days=5)
    quote = _quote_with_item(base, base["product"])
    superuser = CustomUser.objects.create_superuser(email="su@x.uz", username="su@x.uz", password="pw")
    data, err = suggest_quote_pricing(quote.id, superuser)
    assert err is None
    assert len(data["suggestions"]) == 1
    s = data["suggestions"][0]
    assert s["base_price"] == "100.00" and s["currency"] == "USD" and s["lead_time_days"] == 5
    assert s["item_id"] == quote.items.filter(product__isnull=False).first().id


def test_competitor_member_cannot_read_pricing(base):
    _offer(base["product"], base["seller_a"], "100.00", currency=base["usd"])
    quote = _quote_with_item(base, base["product"])  # owned by seller_a
    intruder = CustomUser.objects.create_user(email="b@b.uz", username="b@b.uz", password="pw", is_active=True)
    ws = WorkspaceRole.objects.get_or_create(code="MEMBER", defaults={"name": "M", "sort_order": 10})[0]
    CompanyMember.objects.create(user=intruder, company=base["seller_b"], role=ws, is_active=True, can_sell=True)
    _, err = suggest_quote_pricing(quote.id, intruder)  # member of competitor B
    assert err == "ONLY_SELLER_CAN_BUILD_QUOTE"
