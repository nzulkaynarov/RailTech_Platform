"""Tests for AI draft-КП generation (ADR-0006 Move 3, increment 2).

A routed seller turns the buyer request into a pre-filled draft КП: request lines copied, matched
products' cost prefilled from the seller's SupplierOffer (pricing-assist).
"""

from decimal import Decimal

import pytest

from accounts.models import (
    Company,
    CompanyMember,
    CompanyRole,
    CompanyType,
    CustomUser,
    VerificationStatus,
    WorkspaceRole,
)
from catalog.models import Product, SupplierOffer
from crm.models import Deal, DealSellerRouting, DealStage, Quote, QuoteItem, QuoteStatus
from crm.services.draft_quote import generate_draft_quote
from master_data.models import Currency


@pytest.fixture
def scene(db):
    VerificationStatus.objects.get_or_create(code="L2_VERIFIED", defaults={"name": "L2", "sort_order": 30})
    CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Client", "sort_order": 10})
    CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 20})
    usd = Currency.objects.get_or_create(code="USD", defaults={"name": "USD", "symbol": "$", "sort_order": 10})[0]
    DealStage.objects.get_or_create(code="RFQ_OPEN", defaults={"name": "RFQ", "sort_order": 10})
    draft = QuoteStatus.objects.get_or_create(code="DRAFT", defaults={"name": "Draft", "sort_order": 10})[0]

    buyer = Company.objects.create(name="Buyer", inn="1110000001")
    buyer.types.add(CompanyType.objects.get(code="CLIENT"))
    seller = Company.objects.create(name="Seller", inn="2220000001")
    seller.types.add(CompanyType.objects.get(code="SUPPLIER"))
    # Operational subscription → entitles the seller to ai.draft (baseline) so the gate passes.
    from datetime import timedelta

    from django.utils import timezone

    from accounts.models import SupplierSubscription

    SupplierSubscription.objects.create(
        company=seller,
        plan="BASIC",
        status="ACTIVE",
        valid_from=timezone.now().date(),
        valid_until=(timezone.now() + timedelta(days=365)).date(),
    )

    product = Product.objects.create(name="Автосцепка СА-3")
    SupplierOffer.objects.create(
        product=product, supplier=seller, base_price=Decimal("120.00"), currency=usd, in_stock_lead_time_days=10
    )

    deal = Deal.objects.create(title="RFQ", company=buyer, stage=DealStage.objects.get(code="RFQ_OPEN"))
    DealSellerRouting.objects.create(deal=deal, seller_company=seller)
    # Buyer's request quote (prepared_by=None) with one matched + one free-text line.
    request_quote = Quote.objects.create(deal=deal, version=1, status=draft)
    QuoteItem.objects.create(quote=request_quote, product=product, quantity=5)
    QuoteItem.objects.create(quote=request_quote, quantity=2, imported_raw_name="Тормозная колодка")

    # Seller member who may build КП (quote.edit_pricing) — primary, can_sell.
    role = CompanyRole.objects.create(company=seller, name="Менеджер", permissions=["quote.edit_pricing"])
    ws = WorkspaceRole.objects.get_or_create(code="SALES_MANAGER", defaults={"name": "SM", "sort_order": 10})[0]
    seller_user = CustomUser.objects.create_user(email="s@s.uz", username="s@s.uz", password="pw", is_active=True)
    CompanyMember.objects.create(
        user=seller_user, company=seller, role=ws, company_role=role, is_active=True, is_primary=True, can_sell=True
    )
    return locals()


def test_generate_draft_quote_copies_lines_and_prefills_matched(scene):
    quote, err, prefilled = generate_draft_quote(scene["deal"].id, scene["seller_user"])
    assert err is None
    assert prefilled == 1  # only the matched product line gets a price from the offer
    assert quote.prepared_by_id == scene["seller_user"].id
    assert quote.seller_company_id == scene["seller"].id
    assert quote.status.code == "DRAFT"
    assert quote.version == 2  # request was v1
    items = list(quote.items.all())
    assert len(items) == 2  # both request lines copied
    matched = next(i for i in items if i.product_id)
    assert matched.frozen_base_price == Decimal("120.00")
    assert matched.frozen_currency.code == "USD"
    assert matched.lead_time_days == 10
    assert matched.quantity == 5
    free = next(i for i in items if not i.product_id)
    assert free.imported_raw_name == "Тормозная колодка" and free.frozen_base_price == Decimal("0")


def test_non_routed_seller_denied(scene):
    other_seller = Company.objects.create(name="Other", inn="2220000099")
    other_seller.types.add(CompanyType.objects.get(code="SUPPLIER"))
    role = CompanyRole.objects.create(company=other_seller, name="М", permissions=["quote.edit_pricing"])
    ws = WorkspaceRole.objects.get(code="SALES_MANAGER")
    outsider = CustomUser.objects.create_user(email="o@o.uz", username="o@o.uz", password="pw", is_active=True)
    CompanyMember.objects.create(
        user=outsider, company=other_seller, role=ws, company_role=role, is_active=True, is_primary=True, can_sell=True
    )
    _, err, _ = generate_draft_quote(scene["deal"].id, outsider)
    assert err == "MEMBER_REQUIRED_FOR_ACTION"


def test_no_request_lines(scene):
    empty_deal = Deal.objects.create(title="Empty", company=scene["buyer"], stage=scene["deal"].stage)
    DealSellerRouting.objects.create(deal=empty_deal, seller_company=scene["seller"])
    _, err, _ = generate_draft_quote(empty_deal.id, scene["seller_user"])
    assert err == "NO_REQUEST_LINES"


def test_ai_draft_gated_without_entitlement(scene):
    """A routed seller WITHOUT a subscription/entitlement can't generate an AI draft (paid feature)."""
    seller2 = Company.objects.create(name="Seller2", inn="2220000077")
    seller2.types.add(CompanyType.objects.get(code="SUPPLIER"))  # no subscription, no entitlement
    DealSellerRouting.objects.create(deal=scene["deal"], seller_company=seller2)
    role = CompanyRole.objects.create(company=seller2, name="М", permissions=["quote.edit_pricing"])
    ws = WorkspaceRole.objects.get(code="SALES_MANAGER")
    member = CustomUser.objects.create_user(email="s2@s.uz", username="s2@s.uz", password="pw", is_active=True)
    CompanyMember.objects.create(
        user=member, company=seller2, role=ws, company_role=role, is_active=True, is_primary=True, can_sell=True
    )
    _, err, _ = generate_draft_quote(scene["deal"].id, member)
    assert err == "AI_DRAFT_NOT_ENTITLED"


def test_auto_matches_unmatched_line_by_exact_gost(scene):
    """Move 3: a free-text request line carrying an exact GOST that UNIQUELY matches a PUBLISHED
    product is auto-bound at draft time and gets its price prefilled."""
    from catalog.models import ProductStatus

    pub = ProductStatus.objects.get_or_create(code="PUBLISHED", defaults={"name": "Published", "sort_order": 10})[0]
    koloda = Product.objects.create(name="Тормозная колодка", gost_drawing="ГОСТ 1205-73", status=pub)
    SupplierOffer.objects.create(
        product=koloda,
        supplier=scene["seller"],
        base_price=Decimal("15.00"),
        currency=scene["usd"],
        in_stock_lead_time_days=7,
    )
    free_line = scene["request_quote"].items.get(imported_raw_name="Тормозная колодка")
    free_line.gost_drawing = "ГОСТ 1205-73"
    free_line.save(update_fields=["gost_drawing"])

    quote, err, prefilled = generate_draft_quote(scene["deal"].id, scene["seller_user"])
    assert err is None
    assert prefilled == 2  # the pre-matched line + the newly GOST-matched line
    bound = quote.items.get(gost_drawing="ГОСТ 1205-73")
    assert bound.product_id == koloda.id
    assert bound.frozen_base_price == Decimal("15.00")
    assert bound.lead_time_days == 7


def test_ambiguous_gost_is_not_auto_matched(scene):
    """Move 3 safety: 2+ PUBLISHED products sharing a GOST → the line is left unmatched, never guessed."""
    from catalog.models import ProductStatus

    pub = ProductStatus.objects.get_or_create(code="PUBLISHED", defaults={"name": "Published", "sort_order": 10})[0]
    Product.objects.create(name="Колодка A", gost_drawing="ГОСТ 9999", status=pub)
    Product.objects.create(name="Колодка B", gost_drawing="ГОСТ 9999", status=pub)
    free_line = scene["request_quote"].items.get(imported_raw_name="Тормозная колодка")
    free_line.gost_drawing = "ГОСТ 9999"
    free_line.save(update_fields=["gost_drawing"])

    quote, err, prefilled = generate_draft_quote(scene["deal"].id, scene["seller_user"])
    assert err is None
    unbound = quote.items.get(gost_drawing="ГОСТ 9999")
    assert unbound.product_id is None  # ambiguous → not auto-bound
    assert prefilled == 1  # only the originally pre-matched line
