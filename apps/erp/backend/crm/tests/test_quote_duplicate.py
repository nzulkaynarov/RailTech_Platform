"""G1 — deep-copy a КП (Odoo «Duplicate»).

duplicate_quote clones a Quote into a NEW DRAFT version on the same deal: all line items
(ITEM/SECTION/NOTE, optional flag, position, per-line margin NULL/0 semantics), all document
charges and the КП settings — while NOT copying the send/freeze/approve artefacts and, critically,
re-freezing FX (fx_snapshot / fx_manual EMPTY on the copy). Also covers the endpoint IDOR guard.

Self-contained fixtures (tests run --nomigrations, so every lookup code is seeded here).
"""

from decimal import Decimal

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import Company, CompanyMember, CompanyType, CustomUser, WorkspaceRole
from crm.models import ChargeType, Deal, DealSellerRouting, DealStage, Quote, QuoteCharge, QuoteItem, QuoteStatus
from crm.services import duplicate_quote
from master_data.models import Country

_QUOTES_URL = "/api/v1/crm/quotes/"


@pytest.fixture
def scenario(db):
    DealStage.objects.get_or_create(code="DRAFT", defaults={"name": "DRAFT", "sort_order": 10})
    QuoteStatus.objects.get_or_create(code="DRAFT", defaults={"name": "DRAFT", "sort_order": 10})
    QuoteStatus.objects.get_or_create(code="SENT", defaults={"name": "SENT", "sort_order": 20})
    CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Client", "sort_order": 10})
    CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 20})
    WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})
    uz = Country.objects.get_or_create(code="UZ", defaults={"name": "Uzbekistan", "sort_order": 10})[0]

    def _seller(name, inn):
        co = Company.objects.create(name=name, inn=inn)
        co.types.add(CompanyType.objects.get(code="SUPPLIER"))
        user = CustomUser.objects.create_user(email=f"{inn}@s.test", username=f"{inn}@s.test", password="pw")
        CompanyMember.objects.create(
            user=user, company=co, role=WorkspaceRole.objects.get(code="OWNER"), is_active=True, can_sell=True
        )
        return co, user

    seller, seller_user = _seller("Seller A", "3000000001")
    foreign, foreign_user = _seller("Seller B", "3000000002")

    buyer = Company.objects.create(name="Buyer LLC", inn="6600000001")
    buyer.types.add(CompanyType.objects.get(code="CLIENT"))

    deal = Deal.objects.create(title="Deal", company=buyer, stage=DealStage.objects.get(code="DRAFT"))
    DealSellerRouting.objects.create(deal=deal, seller_company=seller)
    # Foreign seller is co-routed to the SAME deal (hidden competition) — still must not duplicate A's КП.
    DealSellerRouting.objects.create(deal=deal, seller_company=foreign)

    # A SENT (frozen-ish) source КП, owned by seller A, with a full mix of rows + charges + settings.
    source = Quote.objects.create(
        deal=deal,
        version=1,
        status=QuoteStatus.objects.get(code="SENT"),
        prepared_by=seller_user,
        seller_company=seller,
        tax_country=uz,
        vat_rate=Decimal("12.00"),
        margin_percent=Decimal("15.00"),
        delivery_lead_time_days=21,
        delivery_note="в наличии",
        notes="Спасибо за заявку.",
        number="A-КП-2026-00001",
        # These MUST NOT survive the copy.
        fx_snapshot={"USD": "12000"},
        fx_manual={"EUR": "13000"},
    )
    # ITEM with inherited margin (NULL), ITEM with explicit 0, ITEM with explicit 20, an optional
    # ITEM, a SECTION and a NOTE — full display-type + optional + per-line margin coverage.
    QuoteItem.objects.create(
        quote=source,
        display_type="ITEM",
        position=1,
        frozen_base_price=Decimal("100.00"),
        quantity=2,
        margin_percent=None,
        imported_raw_name="line-inherit",
    )
    QuoteItem.objects.create(
        quote=source,
        display_type="ITEM",
        position=2,
        frozen_base_price=Decimal("50.00"),
        quantity=1,
        margin_percent=Decimal("0.00"),
        imported_raw_name="line-zero",
    )
    QuoteItem.objects.create(
        quote=source,
        display_type="ITEM",
        position=3,
        frozen_base_price=Decimal("30.00"),
        quantity=3,
        margin_percent=Decimal("20.00"),
        imported_raw_name="line-20",
    )
    QuoteItem.objects.create(
        quote=source,
        display_type="ITEM",
        position=4,
        frozen_base_price=Decimal("999.00"),
        quantity=1,
        is_optional=True,
        imported_raw_name="opt",
        margin_percent=None,
    )
    QuoteItem.objects.create(quote=source, display_type="SECTION", position=5, imported_raw_name="Раздел")
    QuoteItem.objects.create(quote=source, display_type="NOTE", position=6, imported_raw_name="Заметка")
    freight = ChargeType.objects.get_or_create(code="FREIGHT", defaults={"name": "Фрахт"})[0]
    QuoteCharge.objects.create(quote=source, charge_type=freight, amount=Decimal("40.00"), sort_order=1)
    source.refresh_from_db()
    return {
        "deal": deal,
        "source": source,
        "seller_user": seller_user,
        "foreign_user": foreign_user,
        "seller": seller,
    }


def _auth(user):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
    return client


@pytest.mark.django_db
def test_duplicate_is_new_draft_same_deal_version_plus_one(scenario):
    source = scenario["source"]
    copy = duplicate_quote(source.id, scenario["seller_user"])

    assert copy.id != source.id
    assert copy.deal_id == source.deal_id
    assert copy.version == source.version + 1
    assert copy.status.code == "DRAFT"
    assert copy.seller_company_id == source.seller_company_id


@pytest.mark.django_db
def test_duplicate_copies_items_charges_and_settings(scenario):
    source = scenario["source"]
    copy = duplicate_quote(source.id, scenario["seller_user"])

    # КП settings copied verbatim.
    assert copy.vat_rate == source.vat_rate
    assert copy.tax_country_id == source.tax_country_id
    assert copy.margin_percent == source.margin_percent
    assert copy.delivery_lead_time_days == 21
    assert copy.delivery_note == "в наличии"
    assert copy.notes == "Спасибо за заявку."

    src_items = list(source.items.order_by("position"))
    copy_items = list(copy.items.order_by("position"))
    assert len(copy_items) == len(src_items) == 6
    for original, clone in zip(src_items, copy_items):
        assert clone.id != original.id
        assert clone.display_type == original.display_type
        assert clone.is_optional == original.is_optional
        assert clone.position == original.position
        assert clone.quantity == original.quantity
        assert clone.frozen_base_price == original.frozen_base_price
        assert clone.imported_raw_name == original.imported_raw_name

    # Per-line margin NULL/0/value preserved exactly (DT1 semantics).
    by_name = {item.imported_raw_name: item for item in copy_items}
    assert by_name["line-inherit"].margin_percent is None
    assert by_name["line-zero"].margin_percent == Decimal("0.00")
    assert by_name["line-20"].margin_percent == Decimal("20.00")

    # Charges copied.
    assert copy.charges.count() == 1
    charge = copy.charges.first()
    assert charge.amount == Decimal("40.00")
    assert charge.charge_type_id == source.charges.first().charge_type_id


@pytest.mark.django_db
def test_duplicate_excludes_send_artefacts_and_refreezes_fx(scenario):
    source = scenario["source"]
    copy = duplicate_quote(source.id, scenario["seller_user"])

    # fx_snapshot / fx_manual MUST be empty — the copy re-freezes today's rates on recalc.
    assert copy.fx_snapshot == {}
    assert copy.fx_manual == {}
    # Send / freeze / approve artefacts NOT copied.
    assert copy.number is None
    assert not copy.public_access_token
    assert copy.public_token_revoked is False
    assert copy.first_viewed_at is None
    assert copy.frozen_at is None
    assert copy.approved_at is None
    assert copy.approved_by_id is None
    assert not copy.pdf_file


@pytest.mark.django_db
def test_duplicate_recalculates_totals(scenario):
    source = scenario["source"]
    copy = duplicate_quote(source.id, scenario["seller_user"])
    # Billable lines only (optional/section/note excluded), inherited 15% / explicit 0 / explicit 20:
    #   100*1.15*2 + 50*1.00*1 + 30*1.20*3 = 230 + 50 + 108 = 388.00
    assert copy.subtotal_excl_vat == Decimal("388.00")
    # + freight charge 40 → tax_excl 428; VAT 12% = 51.36; total 479.36.
    assert copy.charges_total == Decimal("40.00")
    assert copy.vat_amount == Decimal("51.36")
    assert copy.total_incl_vat == Decimal("479.36")


@pytest.mark.django_db
def test_endpoint_owner_can_duplicate(scenario):
    client = _auth(scenario["seller_user"])
    resp = client.post(f"{_QUOTES_URL}{scenario['source'].id}/duplicate/")
    assert resp.status_code == 201, resp.content
    assert resp.data["version"] == 2
    assert resp.data["id"] != scenario["source"].id


@pytest.mark.django_db
def test_endpoint_foreign_seller_forbidden(scenario):
    """IDOR: a co-routed competitor (member of a different company) cannot duplicate A's КП."""
    client = _auth(scenario["foreign_user"])
    resp = client.post(f"{_QUOTES_URL}{scenario['source'].id}/duplicate/")
    assert resp.status_code == 403
    assert resp.data["detail"] == "ROLE_NOT_PERMITTED"
    # No new version leaked onto the deal.
    assert Quote.objects.filter(deal=scenario["deal"]).count() == 1
