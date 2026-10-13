"""Track B — ATP auto-split of КП lines by seller stock + catalog lead-time inheritance."""

from decimal import Decimal

import pytest

from catalog.models import Product, ProductStatus, SupplierOffer
from crm.services.availability import Tranche, auto_split_quote_by_availability, split_line_by_availability
from master_data.models import Currency

# ── Pure split rule (no DB needed for the math, but offer is an ORM row) ──────


@pytest.fixture
def offer_factory(db):
    from accounts.models import Company

    usd = Currency.objects.get_or_create(code="USD", defaults={"name": "USD", "symbol": "$"})[0]
    pub = ProductStatus.objects.get_or_create(code="PUBLISHED", defaults={"name": "Published", "sort_order": 10})[0]
    product = Product.objects.create(name="Деталь split", status=pub)
    supplier = Company.objects.create(name="S", inn="9000000001")

    def make(stock, in_stock_days, order_days):
        return SupplierOffer.objects.create(
            product=product,
            supplier=supplier,
            base_price=Decimal("100"),
            currency=usd,
            stock_quantity=stock,
            in_stock_lead_time_days=in_stock_days,
            order_lead_time_days=order_days,
        )

    return product, make


@pytest.mark.django_db
def test_split_qty_exceeds_stock(offer_factory):
    """qty 40, stock 14 (3d / 30d) -> 14@3 + 26@30."""
    product, make = offer_factory
    offer = make(stock=14, in_stock_days=3, order_days=30)
    tranches = split_line_by_availability(product, 40, offer)
    assert tranches == [Tranche(quantity=14, lead_time_days=3), Tranche(quantity=26, lead_time_days=30)]


@pytest.mark.django_db
def test_split_qty_fits_stock(offer_factory):
    """qty 10, stock 14 -> single 10@3 (in-stock lead time)."""
    product, make = offer_factory
    offer = make(stock=14, in_stock_days=3, order_days=30)
    tranches = split_line_by_availability(product, 10, offer)
    assert tranches == [Tranche(quantity=10, lead_time_days=3)]


@pytest.mark.django_db
def test_split_exact_stock_is_single(offer_factory):
    """qty == stock -> single tranche at in-stock lead time (not split)."""
    product, make = offer_factory
    offer = make(stock=14, in_stock_days=3, order_days=30)
    tranches = split_line_by_availability(product, 14, offer)
    assert tranches == [Tranche(quantity=14, lead_time_days=3)]


@pytest.mark.django_db
def test_split_zero_stock_is_order_lead_time(offer_factory):
    """No stock -> single tranche at the order lead time."""
    product, make = offer_factory
    offer = make(stock=0, in_stock_days=3, order_days=30)
    tranches = split_line_by_availability(product, 40, offer)
    assert tranches == [Tranche(quantity=40, lead_time_days=30)]


def test_split_no_offer_is_single_zero():
    """No offer -> one tranche, requested qty at срок 0 (no catalog срок to promise)."""
    tranches = split_line_by_availability(product=None, requested_qty=7, offer=None)
    assert tranches == [Tranche(quantity=7, lead_time_days=0)]


# ── End-to-end: seller builds a КП, submit_for_review auto-splits ────────────


@pytest.fixture
def seller_quote(db):
    from accounts.models import Company, CompanyMember, CompanyType, CustomUser, WorkspaceRole
    from crm.constants import QuoteStatusCode
    from crm.models import Deal, DealStage, Quote, QuoteItem, QuoteStatus

    CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 10})
    supplier_type = CompanyType.objects.get(code="SUPPLIER")
    sales_role = WorkspaceRole.objects.get_or_create(
        code="SALES_MANAGER", defaults={"name": "Sales", "sort_order": 20}
    )[0]
    usd = Currency.objects.get_or_create(code="USD", defaults={"name": "USD", "symbol": "$"})[0]
    pub = ProductStatus.objects.get_or_create(code="PUBLISHED", defaults={"name": "Published", "sort_order": 10})[0]
    draft_qs = QuoteStatus.objects.get_or_create(code=QuoteStatusCode.DRAFT, defaults={"name": "Draft"})[0]
    QuoteStatus.objects.get_or_create(code=QuoteStatusCode.PENDING_APPROVAL, defaults={"name": "Approval"})
    QuoteStatus.objects.get_or_create(code=QuoteStatusCode.PENDING_TRADE_REVIEW, defaults={"name": "Trade"})
    draft_stage = DealStage.objects.get_or_create(code="DRAFT", defaults={"name": "Draft", "sort_order": 0})[0]

    seller_co = Company.objects.create(name="Seller", inn="9000000002")
    seller_co.types.add(supplier_type)
    buyer_co = Company.objects.create(name="Buyer", inn="9000000003")
    seller = CustomUser.objects.create_user(email="s2@s.test", username="s2@s.test", password="pw", is_active=True)
    CompanyMember.objects.create(
        user=seller, company=seller_co, role=sales_role, is_active=True, is_primary=True, can_sell=True
    )

    product = Product.objects.create(name="Колодка", owner_company=seller_co, status=pub)
    SupplierOffer.objects.create(
        product=product,
        supplier=seller_co,
        base_price=Decimal("100"),
        currency=usd,
        stock_quantity=14,
        in_stock_lead_time_days=3,
        order_lead_time_days=30,
    )
    deal = Deal.objects.create(company=buyer_co, stage=draft_stage)
    # Explicit 1:1 USD rate (KP-01): the engine no longer fabricates a silent rate=1 for an
    # unrated line currency, so submit/send would block on FX_RATE_MISSING without a stated rate.
    quote = Quote.objects.create(deal=deal, version=1, status=draft_qs, prepared_by=seller, fx_manual={"USD": "1"})
    item = QuoteItem.objects.create(
        quote=quote,
        product=product,
        quantity=40,
        frozen_base_price=Decimal("100"),
        frozen_currency=usd,
        margin_percent=Decimal("10"),
    )
    return {"seller_co": seller_co, "seller": seller, "quote": quote, "item": item, "product": product}


@pytest.mark.django_db
def test_auto_split_replaces_line_with_tranches(seller_quote):
    quote = seller_quote["quote"]
    created = auto_split_quote_by_availability(quote, seller_quote["seller_co"].id)
    assert created == 1
    lines = list(quote.items.order_by("lead_time_days").values_list("quantity", "lead_time_days"))
    assert lines == [(14, 3), (26, 30)]
    # frozen price + currency cloned identically
    for line in quote.items.all():
        assert line.frozen_base_price == Decimal("100")
        assert line.frozen_currency_id == seller_quote["item"].frozen_currency_id
        assert line.product_id == seller_quote["product"].id


@pytest.mark.django_db
def test_auto_split_is_idempotent(seller_quote):
    quote = seller_quote["quote"]
    first = auto_split_quote_by_availability(quote, seller_quote["seller_co"].id)
    second = auto_split_quote_by_availability(quote, seller_quote["seller_co"].id)
    assert first == 1
    assert second == 0
    assert quote.items.count() == 2


@pytest.mark.django_db
def test_submit_for_review_auto_splits(seller_quote):
    from crm.services.quotes import QuoteLifecycleService

    quote = seller_quote["quote"]
    result, err = QuoteLifecycleService.submit_for_review(quote.id, seller_quote["seller"])
    assert err is None, err
    assert quote.items.count() == 2


@pytest.mark.django_db
def test_manual_lead_time_preserved(seller_quote):
    """A line with a manually-set lead_time still SPLITS by stock, but does not have its
    lead time overwritten by inheritance in reassign — covered by the reassign path."""
    from crm.services.quotes import reassign_quote_item_product

    item = seller_quote["item"]
    item.lead_time_days = 99  # seller set it manually
    item.save(update_fields=["lead_time_days"])
    reassign_quote_item_product(item.id, seller_quote["seller"], seller_quote["product"].id)
    item.refresh_from_db()
    assert item.lead_time_days == 99  # NOT overwritten by catalog inheritance
