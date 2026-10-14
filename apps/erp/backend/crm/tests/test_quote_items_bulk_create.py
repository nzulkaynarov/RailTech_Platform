"""Transactional bulk-CREATE of КП lines (Excel-paste into the builder grid).

The paste will insert 50+ new lines at once; N sequential POSTs would run the cascade N times
and half-commit on a mid-batch failure. POST /api/v1/crm/quote-items/bulk-create/ is
ALL-OR-NOTHING: any invalid row rolls the whole batch back with per-row errors; on success the
cascade + totals recalculate ONCE and the created lines are returned (201).

Guards + field validation mirror the single-item create (seller pricing capability, own-company staff,
frozen КП). Sibling of test_quote_items_bulk_update.py — the update-path counterpart.
"""

from decimal import Decimal
from unittest.mock import patch

import pytest
from django.test import override_settings
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import Company, CompanyMember, CompanyType, CustomUser, SystemRole, WorkspaceRole
from accounts.services.roles import ensure_default_company_roles
from crm.models import Deal, DealStage, Quote, QuoteItem, QuoteStatus
from master_data.models import Currency

BULK_URL = "/api/v1/crm/quote-items/bulk-create/"


@pytest.fixture
def lookups(db):
    WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})
    CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Client", "sort_order": 10})
    CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 20})
    DealStage.objects.get_or_create(code="DRAFT", defaults={"name": "Draft", "sort_order": 10})
    QuoteStatus.objects.get_or_create(code="DRAFT", defaults={"name": "Draft", "sort_order": 10})
    SystemRole.objects.get_or_create(code="ADMIN", defaults={"name": "Admin", "sort_order": 10})
    Currency.objects.get_or_create(code="UZS", defaults={"name": "Узбекский сум", "sort_order": 10})


def _seller(name, inn, email):
    company = Company.objects.create(name=name, inn=inn)
    company.types.add(CompanyType.objects.get(code="SUPPLIER"))
    user = CustomUser.objects.create_user(email=email, username=email, password="x")
    # Роль «Руководитель» → quote.build + quote.edit_pricing (M1-ERP-05: права только из ролей).
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


def _outsider(email):
    """A member of ANOTHER (client) company — legacy OWNER there, but not own-company staff."""
    company = Company.objects.create(name=f"Other {email}", inn=email[:12])
    company.types.add(CompanyType.objects.get(code="CLIENT"))
    user = CustomUser.objects.create_user(email=email, username=email, password="x")
    CompanyMember.objects.create(
        user=user,
        company=company,
        role=WorkspaceRole.objects.get(code="OWNER"),
        is_active=True,
        is_primary=True,
        can_sell=True,
    )
    return user


def _api(user):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
    return client


def _empty_quote(buyer_co, seller_co, *, cost_currency=None):
    """A buyer deal (the own company `seller_co` sells it) with an EMPTY DRAFT quote (bulk-create fills it)."""
    deal = Deal.objects.create(title="КП", company=buyer_co, stage=DealStage.objects.get(code="DRAFT"))
    quote = Quote.objects.create(
        deal=deal,
        version=1,
        status=QuoteStatus.objects.get(code="DRAFT"),
        vat_rate=Decimal("12"),
        subtotal_excl_vat=Decimal("0"),
        vat_amount=Decimal("0"),
        total_incl_vat=Decimal("0"),
        cost_currency_default=cost_currency,
    )
    return deal, quote


@pytest.fixture
def world(lookups):
    seller_user, seller_co = _seller("Seller A", "A100", "sa@t.test")
    buyer_co = Company.objects.create(name="Buyer Co", inn="C100")
    buyer_co.types.add(CompanyType.objects.get(code="CLIENT"))
    return dict(seller_user=seller_user, seller_co=seller_co, buyer_co=buyer_co)


# ── success ───────────────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_bulk_create_success_single_recalc(world):
    """3 new lines insert in one call; the cascade recalculates EXACTLY once; totals reflect them."""
    _deal, quote = _empty_quote(world["buyer_co"], world["seller_co"])
    payload = {
        "quote": quote.id,
        "items": [
            {"imported_raw_name": "Позиция A", "quantity": 2, "frozen_base_price": "150"},
            {"imported_raw_name": "Позиция B", "quantity": 1, "frozen_base_price": "200"},
            {"imported_raw_name": "Позиция C", "quantity": 3, "frozen_base_price": "50"},
        ],
    }

    from crm.services.quotes import QuoteCalculationService

    with patch.object(
        QuoteCalculationService,
        "recalculate_quote",
        side_effect=QuoteCalculationService.recalculate_quote,
    ) as spy:
        resp = _api(world["seller_user"]).post(BULK_URL, payload, format="json")

    assert resp.status_code == 201, resp.content
    assert spy.call_count == 1, "cascade must recalculate ONCE for the whole batch, not per row"

    body = resp.json()
    assert isinstance(body, list) and len(body) == 3
    assert QuoteItem.objects.filter(quote=quote).count() == 3
    by_name = {row["imported_raw_name"]: row for row in body}
    assert by_name["Позиция A"]["quantity"] == 2
    assert Decimal(by_name["Позиция A"]["frozen_base_price"]) == Decimal("150")

    quote.refresh_from_db()
    # subtotal = Σ final_price_excl_vat × qty = 150·2 + 200·1 + 50·3 = 650 (margin/discount = 0)
    assert quote.subtotal_excl_vat == Decimal("650.00")


# ── defaults (qty / currency) ───────────────────────────────────────────────────
@pytest.mark.django_db
def test_bulk_create_applies_defaults(world):
    """A name-only row lands with qty=1, base 0, and the КП's cost_currency_default currency."""
    uzs = Currency.objects.get(code="UZS")
    _deal, quote = _empty_quote(world["buyer_co"], world["seller_co"], cost_currency=uzs)
    payload = {"quote": quote.id, "items": [{"imported_raw_name": "Только имя"}]}

    resp = _api(world["seller_user"]).post(BULK_URL, payload, format="json")

    assert resp.status_code == 201, resp.content
    item = QuoteItem.objects.get(quote=quote)
    assert item.quantity == 1  # model default
    assert item.frozen_base_price == Decimal("0")  # model default
    assert item.frozen_currency_id == uzs.id  # inherited from cost_currency_default


# ── all-or-nothing failure ──────────────────────────────────────────────────────
@pytest.mark.django_db
def test_bulk_create_blank_name_rolls_back_all(world):
    """A single blank-name row fails the WHOLE batch: 400 + per-row code, nothing created."""
    _deal, quote = _empty_quote(world["buyer_co"], world["seller_co"])
    payload = {
        "quote": quote.id,
        "items": [
            {"imported_raw_name": "Валидная", "frozen_base_price": "500"},  # must NOT persist
            {"imported_raw_name": "   ", "quantity": 2},  # blank → invalid
        ],
    }

    resp = _api(world["seller_user"]).post(BULK_URL, payload, format="json")

    assert resp.status_code == 400
    body = resp.json()
    assert body["detail"] == "QUOTE_ITEMS_BULK_INVALID"
    rows = body["rows"]
    assert len(rows) == 1
    assert rows[0]["index"] == 1
    assert "id" not in rows[0]  # new rows have no id yet — index-keyed only
    assert "QUOTE_ITEM_NAME_REQUIRED" in str(rows[0]["errors"]["imported_raw_name"])

    # All-or-nothing: the VALID row 0 was rolled back too — the КП stays empty.
    assert QuoteItem.objects.filter(quote=quote).count() == 0


@pytest.mark.django_db
def test_bulk_create_row_bounds_violation_returns_code(world):
    """A cell violating the model caps surfaces its machine CODE in rows[].errors, nothing created."""
    _deal, quote = _empty_quote(world["buyer_co"], world["seller_co"])
    over_cap = 10**9  # > QUOTE_ITEM_MAX_QUANTITY (1_000_000)
    payload = {
        "quote": quote.id,
        "items": [{"imported_raw_name": "Слишком много", "quantity": over_cap}],
    }

    resp = _api(world["seller_user"]).post(BULK_URL, payload, format="json")

    assert resp.status_code == 400
    body = resp.json()
    assert body["detail"] == "QUOTE_ITEMS_BULK_INVALID"
    assert "QUOTE_ITEM_QTY_TOO_LARGE" in str(body["rows"][0]["errors"]["quantity"])
    assert QuoteItem.objects.filter(quote=quote).count() == 0


# ── guards (mirror single-item create) ───────────────────────────────────────────
@pytest.mark.django_db
def test_bulk_create_outsider_is_refused(world):
    """A non-staff user (member of another company) cannot write the КП — 403 like the single POST."""
    _deal, quote = _empty_quote(world["buyer_co"], world["seller_co"])
    other_user = _outsider("sb@t.test")

    payload = {"quote": quote.id, "items": [{"imported_raw_name": "X"}]}
    resp = _api(other_user).post(BULK_URL, payload, format="json")

    assert resp.status_code == 403
    assert resp.json()["detail"] == "ROLE_NOT_PERMITTED"  # гейт роли (M1-ERP-05)
    assert QuoteItem.objects.filter(quote=quote).count() == 0


@pytest.mark.django_db
def test_bulk_create_frozen_quote_rejected(world):
    """A sent/frozen КП is locked — QUOTE_FROZEN, same lock as the item/charges edits."""
    from django.utils import timezone

    _deal, quote = _empty_quote(world["buyer_co"], world["seller_co"])
    quote.frozen_at = timezone.now()
    quote.save(update_fields=["frozen_at"])

    payload = {"quote": quote.id, "items": [{"imported_raw_name": "X"}]}
    resp = _api(world["seller_user"]).post(BULK_URL, payload, format="json")

    assert resp.status_code == 400
    assert resp.json()["detail"] == "QUOTE_FROZEN"
    assert QuoteItem.objects.filter(quote=quote).count() == 0


@pytest.mark.django_db
@override_settings(QUOTE_ITEMS_BULK_MAX_ROWS=2)
def test_bulk_create_batch_over_limit_rejected(world):
    """A batch above the configured cap is refused wholesale (QUOTE_ITEMS_BULK_TOO_LARGE)."""
    _deal, quote = _empty_quote(world["buyer_co"], world["seller_co"])
    payload = {
        "quote": quote.id,
        "items": [{"imported_raw_name": f"Строка {n}"} for n in range(3)],  # 3 > cap 2
    }
    resp = _api(world["seller_user"]).post(BULK_URL, payload, format="json")

    assert resp.status_code == 400
    assert resp.json()["detail"] == "QUOTE_ITEMS_BULK_TOO_LARGE"
    assert QuoteItem.objects.filter(quote=quote).count() == 0


@pytest.mark.django_db
def test_bulk_create_empty_batch_rejected(world):
    """An empty items list is a malformed request (QUOTE_ITEMS_BULK_EMPTY)."""
    _deal, quote = _empty_quote(world["buyer_co"], world["seller_co"])
    resp = _api(world["seller_user"]).post(BULK_URL, {"quote": quote.id, "items": []}, format="json")

    assert resp.status_code == 400
    assert resp.json()["detail"] == "QUOTE_ITEMS_BULK_EMPTY"
