"""P0 regression (PR #310): the КП line-item list must NEVER be paginated.

QuoteItemViewSet has no page size — the КП builder grid renders every line of a quote
and recomputes economics over all of them. With the global DRF PAGE_SIZE=20 in effect,
a quote with >20 items showed only the first 20 rows in the builder while the totals
still reflected the full set — silent data loss for the seller.

These tests assert the list endpoint returns ALL rows as a BARE array (no {count,results}
pagination envelope), and that the `quote__deal_id` filter still narrows correctly.
"""

from decimal import Decimal

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import Company, CompanyMember, CompanyType, CustomUser, WorkspaceRole
from crm.models import Deal, DealStage, Quote, QuoteItem, QuoteStatus

ITEM_COUNT = 25  # > global DRF PAGE_SIZE (20) — the truncation would have hidden 5 rows.


@pytest.fixture
def lookups(db):
    WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})
    CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Client", "sort_order": 10})
    CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 20})
    DealStage.objects.get_or_create(code="DRAFT", defaults={"name": "Draft", "sort_order": 10})
    QuoteStatus.objects.get_or_create(code="DRAFT", defaults={"name": "Draft", "sort_order": 10})


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
    )
    return client


def _quote_with_items(buyer_co, seller_co, count):
    """A buyer deal routed to `seller_co`, with a quote carrying `count` line items."""
    deal = Deal.objects.create(title="Big КП", company=buyer_co, stage=DealStage.objects.get(code="DRAFT"))
    quote = Quote.objects.create(
        deal=deal,
        version=1,
        status=QuoteStatus.objects.get(code="DRAFT"),
        vat_rate=Decimal("12"),
        subtotal_excl_vat=Decimal("0"),
        vat_amount=Decimal("0"),
        total_incl_vat=Decimal("0"),
    )
    for index in range(count):
        QuoteItem.objects.create(
            quote=quote, imported_raw_name=f"Позиция {index}", quantity=1, final_price_excl_vat=Decimal("0")
        )
    return deal, quote


@pytest.fixture
def world(lookups):
    seller_user, seller_co = _seller("Seller A", "A100", "sa@t.test")
    buyer_co = Company.objects.create(name="Buyer Co", inn="C100")
    buyer_co.types.add(CompanyType.objects.get(code="CLIENT"))
    return dict(seller_user=seller_user, seller_co=seller_co, buyer_co=buyer_co)


@pytest.mark.django_db
def test_list_returns_all_items_unpaginated(world):
    """A quote with 25 items returns all 25 as a bare array — no pagination envelope,
    no truncation at 20."""
    deal, _quote = _quote_with_items(world["buyer_co"], world["seller_co"], ITEM_COUNT)

    resp = _api(world["seller_user"]).get(f"/api/v1/crm/quote-items/?quote__deal_id={deal.id}")
    assert resp.status_code == 200
    body = resp.json()

    # Bare array — NOT a {count, results, next, previous} pagination envelope.
    assert isinstance(body, list), f"expected an unpaginated array, got {type(body).__name__}: {body!r}"
    assert len(body) == ITEM_COUNT, f"expected all {ITEM_COUNT} rows, got {len(body)} (truncated at PAGE_SIZE?)"


@pytest.mark.django_db
def test_quote_deal_id_filter_still_narrows(world):
    """The quote__deal_id filter continues to scope results to a single deal after
    pagination was removed."""
    deal_a, _qa = _quote_with_items(world["buyer_co"], world["seller_co"], ITEM_COUNT)
    deal_b, _qb = _quote_with_items(world["buyer_co"], world["seller_co"], 3)

    resp = _api(world["seller_user"]).get(f"/api/v1/crm/quote-items/?quote__deal_id={deal_a.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    assert len(body) == ITEM_COUNT

    deal_a_item_ids = set(QuoteItem.objects.filter(quote__deal_id=deal_a.id).values_list("id", flat=True))
    assert {row["id"] for row in body} == deal_a_item_ids
    assert deal_b.id != deal_a.id  # sanity: two distinct deals were created
