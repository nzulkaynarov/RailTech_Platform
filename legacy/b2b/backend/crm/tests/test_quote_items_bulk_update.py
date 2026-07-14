"""WP-E (spec-quote-builder-ux-refactor-2026-07-14 §2 P0-4): transactional bulk-update of КП lines.

The builder grid saved N edited lines with N sequential PATCHes — a mid-batch failure left rows
1..N-1 saved and N+1.. not, ran the cascade N times, and reported one generic error. The bulk
endpoint (POST /api/v1/crm/quote-items/bulk-update/) is ALL-OR-NOTHING: any invalid row rolls the
whole batch back with per-row errors; on success the cascade + totals recalculate ONCE.

Guards mirror the single-item PATCH exactly (seller pricing capability, deal routing, frozen КП).
"""

from decimal import Decimal
from unittest.mock import patch

import pytest
from django.test import override_settings
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import (Company, CompanyMember, CompanyType, CustomUser,
                             SystemRole, WorkspaceRole)
from crm.models import (Deal, DealSellerRouting, DealStage, Quote, QuoteItem,
                        QuoteItemHistory, QuoteStatus)

BULK_URL = "/api/v1/crm/quote-items/bulk-update/"


@pytest.fixture
def lookups(db):
    WorkspaceRole.objects.get_or_create(
        code="OWNER", defaults={"name": "Owner", "sort_order": 10}
    )
    CompanyType.objects.get_or_create(
        code="CLIENT", defaults={"name": "Client", "sort_order": 10}
    )
    CompanyType.objects.get_or_create(
        code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 20}
    )
    DealStage.objects.get_or_create(
        code="DRAFT", defaults={"name": "Draft", "sort_order": 10}
    )
    QuoteStatus.objects.get_or_create(
        code="DRAFT", defaults={"name": "Draft", "sort_order": 10}
    )
    SystemRole.objects.get_or_create(
        code="ADMIN", defaults={"name": "Admin", "sort_order": 10}
    )


def _seller(name, inn, email):
    company = Company.objects.create(name=name, inn=inn)
    company.types.add(CompanyType.objects.get(code="SUPPLIER"))
    user = CustomUser.objects.create_user(email=email, username=email, password="x")
    # OWNER WorkspaceRole with no CompanyRole → member_has_permission legacy fallback grants
    # quote.edit_pricing, i.e. can_edit_quote_pricing == True (same as the builder in prod).
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


def _quote_with_items(buyer_co, seller_co, base_prices):
    """A buyer deal routed to `seller_co` with one line per entry in `base_prices` (qty=1)."""
    deal = Deal.objects.create(
        title="КП", company=buyer_co, stage=DealStage.objects.get(code="DRAFT")
    )
    DealSellerRouting.objects.create(deal=deal, seller_company=seller_co)
    quote = Quote.objects.create(
        deal=deal,
        version=1,
        status=QuoteStatus.objects.get(code="DRAFT"),
        vat_rate=Decimal("12"),
        subtotal_excl_vat=Decimal("0"),
        vat_amount=Decimal("0"),
        total_incl_vat=Decimal("0"),
    )
    items = [
        QuoteItem.objects.create(
            quote=quote,
            imported_raw_name=f"Позиция {index}",
            quantity=1,
            frozen_base_price=Decimal(str(price)),
        )
        for index, price in enumerate(base_prices)
    ]
    return deal, quote, items


@pytest.fixture
def world(lookups):
    seller_user, seller_co = _seller("Seller A", "A100", "sa@t.test")
    buyer_co = Company.objects.create(name="Buyer Co", inn="C100")
    buyer_co.types.add(CompanyType.objects.get(code="CLIENT"))
    return dict(seller_user=seller_user, seller_co=seller_co, buyer_co=buyer_co)


# ── success ───────────────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_bulk_update_success_single_recalc(world):
    """3 lines update in one call; the cascade recalculates EXACTLY once; totals reflect the batch."""
    _deal, quote, items = _quote_with_items(
        world["buyer_co"], world["seller_co"], [100, 100, 100]
    )
    payload = {
        "quote": quote.id,
        "items": [
            {"id": items[0].id, "quantity": 2, "frozen_base_price": "150"},
            {"id": items[1].id, "quantity": 1, "frozen_base_price": "200"},
            {"id": items[2].id, "quantity": 3, "frozen_base_price": "50"},
        ],
    }

    from crm.services.quotes import QuoteCalculationService

    with patch.object(
        QuoteCalculationService,
        "recalculate_quote",
        side_effect=QuoteCalculationService.recalculate_quote,
    ) as spy:
        resp = _api(world["seller_user"]).post(BULK_URL, payload, format="json")

    assert resp.status_code == 200, resp.content
    assert (
        spy.call_count == 1
    ), "cascade must recalculate ONCE for the whole batch, not per row"

    body = resp.json()
    assert isinstance(body, list) and len(body) == 3
    by_id = {row["id"]: row for row in body}
    assert by_id[items[0].id]["quantity"] == 2
    assert Decimal(by_id[items[0].id]["frozen_base_price"]) == Decimal("150")

    quote.refresh_from_db()
    # subtotal = Σ final_price_excl_vat × qty = 150·2 + 200·1 + 50·3 = 650 (margin/discount = 0)
    assert quote.subtotal_excl_vat == Decimal("650.00")


@pytest.mark.django_db
def test_bulk_update_writes_history_like_single_patch(world):
    """recalculate_quote snapshots QuoteItemHistory — the bulk path leaves the same audit trail."""
    _deal, quote, items = _quote_with_items(
        world["buyer_co"], world["seller_co"], [100, 100]
    )
    before = QuoteItemHistory.objects.filter(quote_item__quote=quote).count()

    payload = {
        "quote": quote.id,
        "items": [{"id": items[0].id, "frozen_base_price": "300"}],
    }
    resp = _api(world["seller_user"]).post(BULK_URL, payload, format="json")

    assert resp.status_code == 200, resp.content
    assert QuoteItemHistory.objects.filter(quote_item__quote=quote).count() > before


# ── all-or-nothing failure ──────────────────────────────────────────────────────
@pytest.mark.django_db
def test_bulk_update_one_bad_row_rolls_back_all(world):
    """A single over-cap qty fails the WHOLE batch: 400 + per-row errors, nothing persisted."""
    _deal, quote, items = _quote_with_items(
        world["buyer_co"], world["seller_co"], [100, 100]
    )
    over_cap = 10**9  # > QUOTE_ITEM_MAX_QUANTITY (1_000_000)
    payload = {
        "quote": quote.id,
        "items": [
            {
                "id": items[0].id,
                "frozen_base_price": "500",
            },  # valid — must NOT be saved
            {"id": items[1].id, "quantity": over_cap},  # invalid
        ],
    }

    resp = _api(world["seller_user"]).post(BULK_URL, payload, format="json")

    assert resp.status_code == 400
    body = resp.json()
    assert body["detail"] == "QUOTE_ITEMS_BULK_INVALID"
    rows = body["rows"]
    assert len(rows) == 1
    assert rows[0]["id"] == items[1].id
    assert rows[0]["index"] == 1
    assert "QUOTE_ITEM_QTY_TOO_LARGE" in str(rows[0]["errors"]["quantity"])

    # All-or-nothing: the VALID row 0 was rolled back too.
    items[0].refresh_from_db()
    assert items[0].frozen_base_price == Decimal("100")


@pytest.mark.django_db
def test_bulk_update_rejects_item_from_another_quote(world):
    """Every row must belong to the ONE addressed quote — a foreign line is a per-row error."""
    _deal_a, quote_a, items_a = _quote_with_items(
        world["buyer_co"], world["seller_co"], [100]
    )
    _deal_b, _quote_b, items_b = _quote_with_items(
        world["buyer_co"], world["seller_co"], [100]
    )

    payload = {
        "quote": quote_a.id,
        "items": [
            {"id": items_a[0].id, "frozen_base_price": "150"},
            {"id": items_b[0].id, "frozen_base_price": "150"},  # belongs to quote_b
        ],
    }
    resp = _api(world["seller_user"]).post(BULK_URL, payload, format="json")

    assert resp.status_code == 400
    body = resp.json()
    assert body["detail"] == "QUOTE_ITEMS_BULK_INVALID"
    assert body["rows"][0]["id"] == items_b[0].id
    assert "QUOTE_ITEM_NOT_IN_QUOTE" in str(body["rows"][0]["errors"]["id"])
    items_a[0].refresh_from_db()
    assert items_a[0].frozen_base_price == Decimal("100")  # nothing saved


# ── guards (mirror single-item PATCH) ────────────────────────────────────────────
@pytest.mark.django_db
def test_bulk_update_foreign_seller_gets_404(world):
    """A seller NOT routed to the deal cannot reach its КП — 404 like the single PATCH."""
    _deal, quote, items = _quote_with_items(
        world["buyer_co"], world["seller_co"], [100]
    )
    other_user, _other_co = _seller("Seller B", "B200", "sb@t.test")

    payload = {
        "quote": quote.id,
        "items": [{"id": items[0].id, "frozen_base_price": "150"}],
    }
    resp = _api(other_user).post(BULK_URL, payload, format="json")

    assert resp.status_code == 404
    assert resp.json()["detail"] == "QUOTE_NOT_FOUND"
    items[0].refresh_from_db()
    assert items[0].frozen_base_price == Decimal("100")


@pytest.mark.django_db
def test_bulk_update_frozen_quote_rejected(world):
    """A sent/frozen КП is locked — QUOTE_FROZEN, same lock as charges/settings edits."""
    from django.utils import timezone

    _deal, quote, items = _quote_with_items(
        world["buyer_co"], world["seller_co"], [100]
    )
    quote.frozen_at = timezone.now()
    quote.save(update_fields=["frozen_at"])

    payload = {
        "quote": quote.id,
        "items": [{"id": items[0].id, "frozen_base_price": "150"}],
    }
    resp = _api(world["seller_user"]).post(BULK_URL, payload, format="json")

    assert resp.status_code == 400
    assert resp.json()["detail"] == "QUOTE_FROZEN"


@pytest.mark.django_db
def test_bulk_update_platform_admin_viewer_cannot_act(world):
    """Platform-admin viewer never acts on behalf of a company — ADMIN_VIEWER_CANNOT_ACT."""
    admin = CustomUser.objects.create_user(
        email="op@t.test", username="op@t.test", password="x"
    )
    admin.role = SystemRole.objects.get(code="ADMIN")
    admin.save(update_fields=["role"])
    _deal, quote, items = _quote_with_items(
        world["buyer_co"], world["seller_co"], [100]
    )

    payload = {
        "quote": quote.id,
        "items": [{"id": items[0].id, "frozen_base_price": "150"}],
    }
    resp = _api(admin, ctx="").post(BULK_URL, payload, format="json")

    assert resp.status_code == 403
    assert resp.json()["detail"] == "ADMIN_VIEWER_CANNOT_ACT"


@pytest.mark.django_db
@override_settings(QUOTE_ITEMS_BULK_MAX_ROWS=2)
def test_bulk_update_batch_over_limit_rejected(world):
    """A batch above the configured cap is refused wholesale (QUOTE_ITEMS_BULK_TOO_LARGE)."""
    _deal, quote, items = _quote_with_items(
        world["buyer_co"], world["seller_co"], [100, 100, 100]
    )
    payload = {
        "quote": quote.id,
        "items": [
            {"id": item.id, "frozen_base_price": "150"} for item in items
        ],  # 3 > cap 2
    }
    resp = _api(world["seller_user"]).post(BULK_URL, payload, format="json")

    assert resp.status_code == 400
    assert resp.json()["detail"] == "QUOTE_ITEMS_BULK_TOO_LARGE"


@pytest.mark.django_db
def test_bulk_update_empty_batch_rejected(world):
    """An empty items list is a malformed request (QUOTE_ITEMS_BULK_EMPTY)."""
    _deal, quote, _items = _quote_with_items(
        world["buyer_co"], world["seller_co"], [100]
    )
    resp = _api(world["seller_user"]).post(
        BULK_URL, {"quote": quote.id, "items": []}, format="json"
    )

    assert resp.status_code == 400
    assert resp.json()["detail"] == "QUOTE_ITEMS_BULK_EMPTY"


@pytest.mark.django_db
def test_bulk_update_bounds_violations_return_machine_codes(world):
    """Model-bound violations (not only the caps) must surface as machine CODES in
    rows[].errors — the frontend highlights cells by code, never by prose (Rule 2/7)."""
    _deal, quote, items = _quote_with_items(
        world["buyer_co"], world["seller_co"], [100, 100, 100]
    )
    payload = {
        "quote": quote.id,
        "items": [
            {"id": items[0].id, "quantity": 0},
            {"id": items[1].id, "discount_percent": "150"},
            {"id": items[2].id, "frozen_currency": "NO_SUCH_CCY"},
        ],
    }

    resp = _api(world["seller_user"]).post(BULK_URL, payload, format="json")

    assert resp.status_code == 400
    body = resp.json()
    assert body["detail"] == "QUOTE_ITEMS_BULK_INVALID"
    errors_by_id = {row["id"]: row["errors"] for row in body["rows"]}
    assert "QUOTE_ITEM_QTY_INVALID" in str(errors_by_id[items[0].id]["quantity"])
    assert "QUOTE_ITEM_DISCOUNT_INVALID" in str(
        errors_by_id[items[1].id]["discount_percent"]
    )
    assert "CURRENCY_NOT_FOUND" in str(errors_by_id[items[2].id]["frozen_currency"])
