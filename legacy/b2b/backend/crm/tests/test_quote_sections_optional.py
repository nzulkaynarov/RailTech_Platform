"""S1 — секции / заметки / опциональные позиции КП (Odoo-style `display_type`), BACKEND.

Covers the money-critical invariant and the presentation surface:
  • recalculate_quote / economics count ONLY priced, non-optional ITEM rows — SECTION, NOTE and
    optional ITEM lines never enter subtotal / каскад / НДС / маржу;
  • the serializer rejects pricing on SECTION/NOTE (SECTION_NOTE_NO_PRICING);
  • `position` is the explicit row order — the 0062 backfill preserves the pre-migration id order
    and bulk-create appends new rows to the END;
  • the client PDF renders sections with a subtotal, notes in italic, and optional lines in their
    own block AFTER the totals;
  • the bulk-create HTTP route round-trips display_type / is_optional (full APIClient dispatch);
  • back-compat: a plain new line is display_type=ITEM, is_optional=False.

Sibling of test_quote_items_bulk_create.py — reuses the same seller/buyer/quote scaffolding.
"""

import importlib
from decimal import Decimal

import pytest
from django.db import connection
from django.template.loader import render_to_string
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import (
    Company,
    CompanyMember,
    CompanyType,
    CustomUser,
    SystemRole,
    WorkspaceRole,
)
from crm.models import Deal, DealSellerRouting, DealStage, Quote, QuoteItem, QuoteStatus
from crm.serializers import QuoteItemSerializer
from crm.services.documents import client_optional_items, client_projection_items
from crm.services.quotes import QuoteCalculationService, compute_quote_economics
from master_data.models import Currency

BULK_CREATE_URL = "/api/v1/crm/quote-items/bulk-create/"


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


@pytest.fixture
def world(lookups):
    seller_user, seller_co = _seller("Seller A", "A100", "sa@t.test")
    buyer_co = Company.objects.create(name="Buyer Co", inn="C100")
    buyer_co.types.add(CompanyType.objects.get(code="CLIENT"))
    return dict(seller_user=seller_user, seller_co=seller_co, buyer_co=buyer_co)


def _quote(world):
    deal = Deal.objects.create(title="КП", company=world["buyer_co"], stage=DealStage.objects.get(code="DRAFT"))
    DealSellerRouting.objects.create(deal=deal, seller_company=world["seller_co"])
    return Quote.objects.create(
        deal=deal,
        version=1,
        status=QuoteStatus.objects.get(code="DRAFT"),
        vat_rate=Decimal("12"),
        margin_percent=Decimal("0"),
        subtotal_excl_vat=Decimal("0"),
        vat_amount=Decimal("0"),
        total_incl_vat=Decimal("0"),
    )


# ── 1. recalc excludes optional / SECTION / NOTE from all totals + economics ───────────
@pytest.mark.django_db
def test_recalculate_excludes_optional_and_section_note(world):
    """3 priced ITEM + 1 optional ITEM + 1 SECTION + 1 NOTE → subtotal is the Σ of the 3 ITEM only;
    VAT/total follow; economics COGS ignores the optional line and the presentation rows."""
    quote = _quote(world)
    # priced lines: 100·2 + 200·1 + 50·3 = 550
    QuoteItem.objects.create(
        quote=quote, imported_raw_name="A", quantity=2, frozen_base_price=Decimal("100"), position=0
    )
    QuoteItem.objects.create(
        quote=quote, imported_raw_name="B", quantity=1, frozen_base_price=Decimal("200"), position=1
    )
    QuoteItem.objects.create(
        quote=quote, imported_raw_name="C", quantity=3, frozen_base_price=Decimal("50"), position=2
    )
    # optional priced line — big price, MUST NOT enter the totals or COGS.
    QuoteItem.objects.create(
        quote=quote,
        imported_raw_name="Опция",
        quantity=1,
        frozen_base_price=Decimal("1000"),
        is_optional=True,
        position=3,
    )
    QuoteItem.objects.create(quote=quote, display_type="SECTION", imported_raw_name="Раздел", position=4)
    QuoteItem.objects.create(quote=quote, display_type="NOTE", imported_raw_name="Заметка", position=5)

    QuoteCalculationService.recalculate_quote(quote.pk)
    quote.refresh_from_db()

    assert quote.subtotal_excl_vat == Decimal("550.00")  # NOT 1550 — optional excluded
    assert quote.vat_amount == Decimal("66.00")  # 550 × 12%
    assert quote.total_incl_vat == Decimal("616.00")

    econ = compute_quote_economics(quote)
    assert econ["total_landed_cost"] == Decimal("550.00")  # optional's 1000 excluded from COGS
    assert econ["gross_profit"] == Decimal("0.00")  # margin 0 → price == cost over the 3 lines


# ── 2. SECTION / NOTE reject pricing ───────────────────────────────────────────────────
@pytest.mark.django_db
def test_section_rejects_pricing_field(world):
    quote = _quote(world)
    ser = QuoteItemSerializer(
        data={"quote": quote.id, "display_type": "SECTION", "imported_raw_name": "Р", "frozen_base_price": "500"}
    )
    assert not ser.is_valid()
    assert ser.errors["frozen_base_price"] == ["SECTION_NOTE_NO_PRICING"]


@pytest.mark.django_db
def test_note_cannot_be_optional(world):
    quote = _quote(world)
    ser = QuoteItemSerializer(
        data={"quote": quote.id, "display_type": "NOTE", "imported_raw_name": "N", "is_optional": True}
    )
    assert not ser.is_valid()
    assert ser.errors["is_optional"] == ["SECTION_NOTE_NO_PRICING"]


@pytest.mark.django_db
def test_section_with_zero_pricing_is_valid(world):
    quote = _quote(world)
    ser = QuoteItemSerializer(
        data={"quote": quote.id, "display_type": "SECTION", "imported_raw_name": "Р", "frozen_base_price": "0"}
    )
    assert ser.is_valid(), ser.errors


# ── 3. position backfill (migration 0062) preserves the pre-migration id order ──────────
@pytest.mark.django_db
def test_position_backfill_preserves_id_order(world):
    """Force every row to position=0 (the pre-migration state) then run the ACTUAL 0062 backfill
    function; it must renumber 0,1,2 per quote in id order — the order sellers already saw."""
    quote = _quote(world)
    first = QuoteItem.objects.create(quote=quote, imported_raw_name="1", frozen_base_price=Decimal("10"))
    second = QuoteItem.objects.create(quote=quote, imported_raw_name="2", frozen_base_price=Decimal("20"))
    third = QuoteItem.objects.create(quote=quote, imported_raw_name="3", frozen_base_price=Decimal("30"))
    QuoteItem.objects.filter(quote=quote).update(position=0)  # simulate pre-0062 rows

    migration = importlib.import_module("crm.migrations.0062_alter_quoteitem_options_and_more")

    class _SchemaEditor:
        def execute(self, sql):
            with connection.cursor() as cursor:
                cursor.execute(sql)

    migration.backfill_position(None, _SchemaEditor())

    first.refresh_from_db()
    second.refresh_from_db()
    third.refresh_from_db()
    assert (first.position, second.position, third.position) == (0, 1, 2)


# ── 4. bulk-create appends new rows to the END (max position + 1..N), keeping paste order ──
@pytest.mark.django_db
def test_bulk_create_appends_positions_to_end(world):
    quote = _quote(world)
    # An existing row already at position 5.
    QuoteItem.objects.create(quote=quote, imported_raw_name="старая", frozen_base_price=Decimal("10"), position=5)

    payload = {
        "quote": quote.id,
        "items": [
            {"imported_raw_name": "новая-1", "frozen_base_price": "100"},
            {"imported_raw_name": "новая-2", "frozen_base_price": "200"},
        ],
    }
    resp = _api(world["seller_user"]).post(BULK_CREATE_URL, payload, format="json")
    assert resp.status_code == 201, resp.content

    positions = {i.imported_raw_name: i.position for i in QuoteItem.objects.filter(quote=quote)}
    assert positions["новая-1"] == 6  # max(5) + 1
    assert positions["новая-2"] == 7  # preserves paste order, at the end


# ── 5. PDF renders section subtotal, italic note, and a separate optional block ────────
@pytest.mark.django_db
def test_pdf_renders_sections_notes_and_optional_block(world):
    quote = _quote(world)
    QuoteItem.objects.create(quote=quote, display_type="SECTION", imported_raw_name="РАЗДЕЛ ОДИН", position=0)
    QuoteItem.objects.create(
        quote=quote, imported_raw_name="Позиция под разделом", quantity=2, frozen_base_price=Decimal("100"), position=1
    )
    QuoteItem.objects.create(quote=quote, display_type="NOTE", imported_raw_name="Важная заметка курсивом", position=2)
    QuoteItem.objects.create(
        quote=quote,
        imported_raw_name="Доп. позиция",
        quantity=1,
        frozen_base_price=Decimal("500"),
        is_optional=True,
        position=3,
    )
    QuoteCalculationService.recalculate_quote(quote.pk)
    quote.refresh_from_db()

    rows = client_projection_items(quote)
    optional = client_optional_items(quote)
    # Projection: section subtotal = Σ of its ITEM line(s) = 200; optional excluded from `rows`.
    section = next(r for r in rows if r["display_type"] == "SECTION")
    assert section["section_subtotal"] == Decimal("200.00")
    assert all(not r.get("is_optional") for r in rows if r["display_type"] == "ITEM")
    assert [o["imported_raw_name"] for o in optional] == ["Доп. позиция"]

    html = render_to_string(
        "crm/quote_pdf.html",
        {
            "quote": quote,
            "items": rows,
            "optional_items": optional,
            "company": world["buyer_co"],
            "seller": world["seller_co"],
            "seller_profile": None,
            "seller_logo_url": None,
            "is_demo": False,
            "show_lead_time": True,
            "accent": "#15294d",
            "accent_contrast": "#ffffff",
        },
    )
    assert "РАЗДЕЛ ОДИН" in html
    assert "section-row" in html  # section styled row is present
    assert "Важная заметка курсивом" in html
    assert "note-row" in html  # italic note row
    assert "Опционально (не входит в итог)" in html  # optional block heading
    assert "Доп. позиция" in html
    # The optional line's 500 is NOT part of the grand total (200 + 12% VAT = 224).
    assert quote.total_incl_vat == Decimal("224.00")


# ── 6. bulk-create HTTP round-trips display_type / is_optional (full dispatch) ─────────
@pytest.mark.django_db
def test_bulk_create_http_display_type_and_optional(world):
    quote = _quote(world)
    payload = {
        "quote": quote.id,
        "items": [
            {"imported_raw_name": "РАЗДЕЛ", "display_type": "SECTION"},
            {"imported_raw_name": "Обычная", "quantity": 1, "frozen_base_price": "300"},
            {"imported_raw_name": "Опция", "quantity": 1, "frozen_base_price": "999", "is_optional": True},
        ],
    }
    resp = _api(world["seller_user"]).post(BULK_CREATE_URL, payload, format="json")
    assert resp.status_code == 201, resp.content

    section = QuoteItem.objects.get(quote=quote, imported_raw_name="РАЗДЕЛ")
    assert section.display_type == "SECTION"
    assert section.final_price_excl_vat == Decimal("0")  # SECTION carries no price
    optional = QuoteItem.objects.get(quote=quote, imported_raw_name="Опция")
    assert optional.is_optional is True

    quote.refresh_from_db()
    # Only the plain 300 line feeds the subtotal — SECTION + optional excluded.
    assert quote.subtotal_excl_vat == Decimal("300.00")


# ── 7. back-compat: a plain new line defaults to ITEM / not-optional ───────────────────
@pytest.mark.django_db
def test_new_line_defaults_to_item(world):
    quote = _quote(world)
    item = QuoteItem.objects.create(quote=quote, imported_raw_name="обычная", frozen_base_price=Decimal("10"))
    assert item.display_type == "ITEM"
    assert item.is_optional is False
