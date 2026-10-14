"""DT2 — the documented shape of `economics` must match what the service really returns.

`Quote.economics` used to be an untyped `SerializerMethodField`: it landed in OpenAPI as an
opaque `{[key]: unknown}`, so `below_floor` / `below_cost` / `min_margin_percent` — live
below-floor-gate business logic the SPA branches on — did not appear in the generated
`frontend/src/api/schema.d.ts` at all. Backend and frontend could drift with NO CI signal.

`QuoteEconomicsSerializer` now documents that shape via `@extend_schema_field`. These tests are
the thing that stops the annotation from rotting: they compare the declared fields against the
REAL output of `compute_quote_economics()` — key set AND per-key wire type — and cover both
`None` branches of the cost gate.
"""

from decimal import Decimal

import pytest
from rest_framework.test import APIRequestFactory

from accounts.models import Company, CompanyMember, CompanySettings, CompanyType, CustomUser, SystemRole, WorkspaceRole
from accounts.services.roles import ensure_default_company_roles
from crm.models import Deal, DealStage, Quote, QuoteItem, QuoteStatus
from crm.serializers.quote import QuoteEconomicsSerializer, QuoteSerializer
from crm.services.quotes import QuoteCalculationService, compute_quote_economics
from master_data.models import Currency

# The 11 keys of the single unconditional `return` in compute_quote_economics(). Spelled out
# literally (not derived from either side) so a rename on EITHER side breaks this test.
EXPECTED_KEYS = {
    "total_landed_cost",
    "gross_profit",
    "gross_margin_percent",
    "markup_percent",
    "charge_cost_total",
    "operating_profit",
    "below_cost",
    "below_floor",
    "min_margin_percent",
    "target_margin_percent",
    "fx_missing",
}
# Wire types AFTER get_economics() stringifies every Decimal.
BOOL_KEYS = {"below_cost", "below_floor"}
LIST_KEYS = {"fx_missing"}
STR_KEYS = EXPECTED_KEYS - BOOL_KEYS - LIST_KEYS


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
        company_roles=[ensure_default_company_roles(company)["HEAD"]],
    )
    return user, company


@pytest.fixture
def world(lookups):
    seller_user, seller_co = _seller("Seller A", "A100", "econ-seller@t.test")
    buyer_co = Company.objects.create(name="Buyer Co", inn="C100")
    buyer_co.types.add(CompanyType.objects.get(code="CLIENT"))
    return dict(seller_user=seller_user, seller_co=seller_co, buyer_co=buyer_co)


def _quote(world, *, owned=True):
    """`owned=True` anchors the КП to the seller company + preparer, which is what makes
    `_quote_owner_company_id()` resolve (→ real CompanySettings thresholds) and what arms the
    per-quote cost gate. `owned=False` is the unclaimed buyer request: no owner, no preparer."""
    deal = Deal.objects.create(title="КП", company=world["buyer_co"], stage=DealStage.objects.get(code="DRAFT"))
    return Quote.objects.create(
        deal=deal,
        version=1,
        status=QuoteStatus.objects.get(code="DRAFT"),
        vat_rate=Decimal("12"),
        margin_percent=Decimal("0"),
        subtotal_excl_vat=Decimal("0"),
        vat_amount=Decimal("0"),
        total_incl_vat=Decimal("0"),
        seller_company=world["seller_co"] if owned else None,
        prepared_by=world["seller_user"] if owned else None,
    )


def _serialize(quote, user, include_economics=True):
    request = APIRequestFactory().get("/")
    request.user = user
    return QuoteSerializer(quote, context={"request": request, "include_economics": include_economics}).data


# ── 1. declared fields == service keys, exactly ────────────────────────────────────────
@pytest.mark.django_db
def test_documented_fields_match_service_keys(world):
    """The annotation is only useful if it is EXHAUSTIVE and has no phantom keys."""
    quote = _quote(world)
    QuoteItem.objects.create(quote=quote, imported_raw_name="A", quantity=2, frozen_base_price=Decimal("100"))
    QuoteCalculationService.recalculate_quote(quote.pk)
    quote.refresh_from_db()

    declared = set(QuoteEconomicsSerializer().fields)
    actual = set(compute_quote_economics(quote))

    assert declared == EXPECTED_KEYS, "QuoteEconomicsSerializer drifted from the documented contract"
    assert actual == EXPECTED_KEYS, "compute_quote_economics() drifted from the documented contract"
    assert declared == actual


# ── 2. wire types match the declared field types ───────────────────────────────────────
@pytest.mark.django_db
def test_serialized_economics_types_match_declaration(world):
    """Decimals are stringified by get_economics → the schema must say string, not number."""
    quote = _quote(world)
    QuoteItem.objects.create(quote=quote, imported_raw_name="A", quantity=2, frozen_base_price=Decimal("100"))
    QuoteCalculationService.recalculate_quote(quote.pk)
    quote.refresh_from_db()

    economics = _serialize(quote, world["seller_user"])["economics"]
    assert economics is not None
    assert set(economics) == EXPECTED_KEYS

    for key in STR_KEYS:
        assert isinstance(economics[key], str), f"{key} must reach the client as a string"
    for key in BOOL_KEYS:
        assert isinstance(economics[key], bool), f"{key} must reach the client as a boolean"
    for key in LIST_KEYS:
        assert isinstance(economics[key], list), f"{key} must reach the client as a list"
        assert all(isinstance(code, str) for code in economics[key])


# ── 3. the below-floor gate keys carry real values, not placeholders ───────────────────
@pytest.mark.django_db
def test_below_floor_reflects_company_threshold(world):
    """The keys the SPA branches on must actually track CompanySettings — the whole reason
    DT2 matters: a silent rename here would disable the gate in the seller's face."""
    CompanySettings.objects.update_or_create(
        company=world["seller_co"],
        defaults={"min_margin_percent": Decimal("40"), "target_margin_percent": Decimal("60")},
    )
    quote = _quote(world)
    # margin_percent=0 → price == landed cost → 0% gross margin, far below the 40% floor.
    QuoteItem.objects.create(quote=quote, imported_raw_name="A", quantity=2, frozen_base_price=Decimal("100"))
    QuoteCalculationService.recalculate_quote(quote.pk)
    quote.refresh_from_db()

    economics = _serialize(quote, world["seller_user"])["economics"]
    assert economics["min_margin_percent"] == "40.00"
    assert economics["target_margin_percent"] == "60.00"
    assert economics["below_floor"] is True
    assert economics["below_cost"] is False  # price covers cost exactly — a floor miss, not a loss


@pytest.mark.django_db
def test_margin_thresholds_fall_back_when_quote_has_no_owner(world):
    """Second branch of the threshold lookup: an unclaimed КП resolves to no company, so the
    service falls back to the hardcoded defaults. NOTE the fallback stringifies as "15"/"25"
    while a CompanySettings row gives "15.00"/"25.00" — both are strings (so the declared
    CharField holds), but a consumer must parse, never string-compare, these values."""
    quote = _quote(world, owned=False)
    QuoteItem.objects.create(quote=quote, imported_raw_name="A", quantity=2, frozen_base_price=Decimal("100"))
    QuoteCalculationService.recalculate_quote(quote.pk)
    quote.refresh_from_db()

    economics = _serialize(quote, world["seller_user"])["economics"]
    assert economics["min_margin_percent"] == "15"
    assert economics["target_margin_percent"] == "25"
    assert set(economics) == EXPECTED_KEYS  # fallback branch returns the SAME key set


# ── 4. both None branches — the reason the field is nullable ───────────────────────────
@pytest.mark.django_db
def test_economics_is_none_without_include_flag(world):
    """List endpoints don't ask for economics → None (keeps it off list responses, no N+1)."""
    quote = _quote(world)
    assert _serialize(quote, world["seller_user"], include_economics=False)["economics"] is None


@pytest.mark.django_db
def test_economics_is_none_for_viewer_without_cost_visibility(world):
    """Cost gate: a viewer without `quote.view_cost_margin` in the own company — a staff member
    with a restricted role, or the deal's buyer — sees economics=None, never a partial object.
    This is why the schema marks the OBJECT nullable rather than its individual fields."""
    from accounts.models import CompanyRole

    restricted_role = CompanyRole.objects.create(company=world["seller_co"], name="Без прав", permissions=[])
    restricted = CustomUser.objects.create_user(email="econ-viewer@t.test", username="econ-viewer@t.test", password="x")
    CompanyMember.objects.create(
        user=restricted,
        company=world["seller_co"],
        role=WorkspaceRole.objects.get(code="OWNER"),
        company_roles=[restricted_role],
        is_active=True,
        can_sell=True,
    )
    buyer = CustomUser.objects.create_user(email="econ-buyer@t.test", username="econ-buyer@t.test", password="x")
    CompanyMember.objects.create(
        user=buyer, company=world["buyer_co"], role=WorkspaceRole.objects.get(code="OWNER"), is_active=True
    )
    quote = _quote(world)
    QuoteItem.objects.create(quote=quote, imported_raw_name="A", quantity=2, frozen_base_price=Decimal("100"))
    QuoteCalculationService.recalculate_quote(quote.pk)
    quote.refresh_from_db()

    assert _serialize(quote, restricted)["economics"] is None
    assert _serialize(quote, buyer)["economics"] is None
    assert _serialize(quote, world["seller_user"])["economics"] is not None  # control: the gate opens
