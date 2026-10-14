"""Optimistic locking on QuoteItem (spec §5.3, волна 3) — защита от тихого затирания правок.

Two managers editing the same КП must not silently clobber each other's saves. Every row carries
a `version` counter (default 0); a save that presents a STALE version (the колега already saved,
bumping it) is rejected with QUOTE_ITEM_STALE instead of overwriting the committed edit:

  • bulk-update — per-row error in the QUOTE_ITEMS_BULK_INVALID rows[].errors shape; ALL-OR-NOTHING
    (one stale row → the whole transactional batch rolls back, nothing applied);
  • single PATCH — 409 QUOTE_ITEM_STALE.

A successful save bumps the version (N → N+1). New rows (bulk-create) are NOT version-gated.
`version` is OPTIONAL in the payload — a version-less save keeps the pre-волна-3 last-write-wins
behaviour (covered by the existing bulk-update suite, which sends no version).
"""

from decimal import Decimal

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import Company, CompanyMember, CompanyType, CustomUser, SystemRole, WorkspaceRole
from accounts.services.roles import ensure_default_company_roles
from crm.models import Deal, DealStage, Quote, QuoteItem, QuoteStatus

BULK_UPDATE_URL = "/api/v1/crm/quote-items/bulk-update/"
BULK_CREATE_URL = "/api/v1/crm/quote-items/bulk-create/"


@pytest.fixture
def lookups(db):
    WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})
    CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Client", "sort_order": 10})
    CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 20})
    DealStage.objects.get_or_create(code="DRAFT", defaults={"name": "Draft", "sort_order": 10})
    QuoteStatus.objects.get_or_create(code="DRAFT", defaults={"name": "Draft", "sort_order": 10})
    SystemRole.objects.get_or_create(code="ADMIN", defaults={"name": "Admin", "sort_order": 10})


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
        company_roles=[ensure_default_company_roles(company)["HEAD"]],
    )
    return user, company


def _api(user, ctx="SELLER"):
    client = APIClient()
    client.credentials(
        HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}",
    )
    return client


def _quote_with_items(buyer_co, seller_co, base_prices):
    deal = Deal.objects.create(title="КП", company=buyer_co, stage=DealStage.objects.get(code="DRAFT"))
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


# ── bulk-update ────────────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_bulk_update_matching_version_succeeds_and_bumps(world):
    """Correct version (N) → save applies and the row's version becomes N+1 in the response + DB."""
    _deal, quote, items = _quote_with_items(world["buyer_co"], world["seller_co"], [100])
    assert items[0].version == 0
    payload = {
        "quote": quote.id,
        "items": [{"id": items[0].id, "version": 0, "frozen_base_price": "150"}],
    }
    resp = _api(world["seller_user"]).post(BULK_UPDATE_URL, payload, format="json")

    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body[0]["version"] == 1
    items[0].refresh_from_db()
    assert items[0].version == 1
    assert items[0].frozen_base_price == Decimal("150")


@pytest.mark.django_db
def test_bulk_update_stale_version_rejected_nothing_saved(world):
    """A stale version (N-1 after a colleague already saved N) → per-row QUOTE_ITEM_STALE, no write."""
    _deal, quote, items = _quote_with_items(world["buyer_co"], world["seller_co"], [100])
    # Simulate a colleague's save: the row is now at version 1.
    QuoteItem.objects.filter(pk=items[0].id).update(version=1, frozen_base_price=Decimal("999"))

    payload = {
        "quote": quote.id,
        # Our client still believes the row is at version 0 → stale.
        "items": [{"id": items[0].id, "version": 0, "frozen_base_price": "150"}],
    }
    resp = _api(world["seller_user"]).post(BULK_UPDATE_URL, payload, format="json")

    assert resp.status_code == 400
    body = resp.json()
    assert body["detail"] == "QUOTE_ITEMS_BULK_INVALID"
    assert "QUOTE_ITEM_STALE" in str(body["rows"][0]["errors"]["version"])
    # Nothing overwritten — the colleague's 999 stands.
    items[0].refresh_from_db()
    assert items[0].frozen_base_price == Decimal("999")
    assert items[0].version == 1


@pytest.mark.django_db
def test_bulk_update_one_stale_row_rolls_back_whole_batch(world):
    """One stale row → the ENTIRE transactional batch is rejected (all-or-nothing), nothing saved."""
    _deal, quote, items = _quote_with_items(world["buyer_co"], world["seller_co"], [100, 100])
    # Row 1 was saved by a colleague (now version 1); row 0 is still fresh (version 0).
    QuoteItem.objects.filter(pk=items[1].id).update(version=1)

    payload = {
        "quote": quote.id,
        "items": [
            {"id": items[0].id, "version": 0, "frozen_base_price": "150"},  # valid — must NOT save
            {"id": items[1].id, "version": 0, "frozen_base_price": "150"},  # stale
        ],
    }
    resp = _api(world["seller_user"]).post(BULK_UPDATE_URL, payload, format="json")

    assert resp.status_code == 400
    body = resp.json()
    assert body["detail"] == "QUOTE_ITEMS_BULK_INVALID"
    stale = {row["id"]: row for row in body["rows"]}[items[1].id]
    assert "QUOTE_ITEM_STALE" in str(stale["errors"]["version"])
    # All-or-nothing: the valid fresh row 0 was rolled back too, and its version did NOT bump.
    items[0].refresh_from_db()
    assert items[0].frozen_base_price == Decimal("100")
    assert items[0].version == 0


@pytest.mark.django_db
def test_bulk_update_without_version_keeps_last_write_wins(world):
    """A version-less payload skips the optimistic check (backward compat) — still saves + bumps."""
    _deal, quote, items = _quote_with_items(world["buyer_co"], world["seller_co"], [100])
    payload = {"quote": quote.id, "items": [{"id": items[0].id, "frozen_base_price": "150"}]}
    resp = _api(world["seller_user"]).post(BULK_UPDATE_URL, payload, format="json")

    assert resp.status_code == 200, resp.content
    items[0].refresh_from_db()
    assert items[0].frozen_base_price == Decimal("150")
    # Even a version-less save bumps the counter so the next concurrent editor is protected.
    assert items[0].version == 1


# ── single PATCH ───────────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_single_patch_stale_version_conflicts(world):
    """A single-line PATCH with a stale version → 409 QUOTE_ITEM_STALE, nothing overwritten."""
    _deal, _quote, items = _quote_with_items(world["buyer_co"], world["seller_co"], [100])
    QuoteItem.objects.filter(pk=items[0].id).update(version=1, frozen_base_price=Decimal("999"))

    resp = _api(world["seller_user"]).patch(
        f"/api/v1/crm/quote-items/{items[0].id}/",
        {"version": 0, "frozen_base_price": "150"},
        format="json",
    )

    assert resp.status_code == 409
    assert resp.json()["detail"] == "QUOTE_ITEM_STALE"
    items[0].refresh_from_db()
    assert items[0].frozen_base_price == Decimal("999")


@pytest.mark.django_db
def test_single_patch_matching_version_succeeds_and_bumps(world):
    """A single-line PATCH with the current version → saved and version N→N+1."""
    _deal, _quote, items = _quote_with_items(world["buyer_co"], world["seller_co"], [100])
    resp = _api(world["seller_user"]).patch(
        f"/api/v1/crm/quote-items/{items[0].id}/",
        {"version": 0, "frozen_base_price": "150"},
        format="json",
    )

    assert resp.status_code == 200, resp.content
    assert resp.json()["version"] == 1
    items[0].refresh_from_db()
    assert items[0].version == 1
    assert items[0].frozen_base_price == Decimal("150")


# ── bulk-create is NOT version-gated ─────────────────────────────────────────────
@pytest.mark.django_db
def test_bulk_create_new_rows_not_version_gated(world):
    """New lines carry no id/version yet — bulk-create must ignore the optimistic check entirely."""
    _deal, quote, _items = _quote_with_items(world["buyer_co"], world["seller_co"], [100])
    payload = {
        "quote": quote.id,
        "items": [{"imported_raw_name": "Новая строка", "quantity": 2, "frozen_base_price": "42"}],
    }
    resp = _api(world["seller_user"]).post(BULK_CREATE_URL, payload, format="json")

    assert resp.status_code == 201, resp.content
    body = resp.json()
    assert len(body) == 1
    assert body[0]["imported_raw_name"] == "Новая строка"
    # A freshly-created row starts at version 0.
    assert body[0]["version"] == 0


# ── B4: the single PATCH must be a real critical section, not a read-then-write race ──
@pytest.mark.django_db
def test_single_patch_locks_the_row_before_reading_version(world):
    """TOCTOU: the version read and the increment must happen under a row lock, in one
    transaction — otherwise two concurrent PATCHes both read version N, both pass the check and
    the later save silently clobbers the earlier one (the bulk path always did this; the single
    path read with a plain SELECT and wrote outside any transaction).

    Asserted on the emitted SQL because a thread-race test would be non-deterministic: a
    `SELECT ... FOR UPDATE` on the line must precede the `UPDATE`, so a racing request blocks
    until our increment is committed and then sees the bumped version (→ 409, covered above)."""
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    _deal, _quote, items = _quote_with_items(world["buyer_co"], world["seller_co"], [100])

    with CaptureQueriesContext(connection) as captured:
        resp = _api(world["seller_user"]).patch(
            f"/api/v1/crm/quote-items/{items[0].id}/",
            {"version": 0, "frozen_base_price": "150"},
            format="json",
        )

    assert resp.status_code == 200, resp.content
    table_name = QuoteItem._meta.db_table
    statements = [query["sql"].lower() for query in captured.captured_queries]
    lock_at = next(
        (i for i, sql in enumerate(statements) if table_name in sql and "for update" in sql),
        None,
    )
    write_at = next(
        (i for i, sql in enumerate(statements) if sql.startswith("update") and table_name in sql),
        None,
    )
    assert lock_at is not None, "single PATCH did not lock the line — the TOCTOU race is open"
    assert write_at is not None
    assert lock_at < write_at, "the row lock must be taken BEFORE the version read and the write"
    items[0].refresh_from_db()
    assert items[0].version == 1
