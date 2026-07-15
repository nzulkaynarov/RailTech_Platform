"""Quote.fx_market — preliminary market FX rates for the frontend pricing mirror.

usePricingMirror recomputes КП lines locally, but for a cost currency not yet frozen in
Quote.fx_snapshot / fx_manual the frontend had no rate → «пересчёт после сохранения». The
read-only fx_market map exposes the current market rate_to_uzs for every ACTIVE currency
(UZS = 1) so the mirror can preview the line. Rates come from the LOCAL ExchangeRate table
(master_data.fx.get_rate_to_uzs) — no network in the request path. A currency with no known
rate is OMITTED, so the mirror keeps its honest «no rate» marker.
"""

import datetime
from decimal import Decimal

import pytest

from accounts.models import Company, CustomUser
from crm.models import Deal, DealStage, Quote, QuoteStatus
from crm.serializers import QuoteSerializer
from master_data.models import Currency, ExchangeRate


@pytest.fixture
def quote(db):
    # DRAFT stage/status are seeded by data migrations (Rule 1) — get_or_create, never create.
    stage, _ = DealStage.objects.get_or_create(code="DRAFT", defaults={"name": "Draft", "sort_order": 10})
    status, _ = QuoteStatus.objects.get_or_create(code="DRAFT", defaults={"name": "Draft", "sort_order": 10})
    buyer = Company.objects.create(name="Buyer Co", inn="C900")
    deal = Deal.objects.create(title="КП", company=buyer, stage=stage)
    return Quote.objects.create(
        deal=deal,
        version=1,
        status=status,
        vat_rate=Decimal("12"),
        subtotal_excl_vat=Decimal("0"),
        vat_amount=Decimal("0"),
        total_incl_vat=Decimal("0"),
    )


def _currency(code, *, is_active):
    """Ensure a Currency lookup exists with the wanted active flag (some are seeded)."""
    currency, _ = Currency.objects.update_or_create(code=code, defaults={"name": code, "is_active": is_active})
    return currency


def _serialize(quote, *, include_economics=True):
    """Serialize with an authenticated request in context (fx_market is user-independent).

    fx_market shares the include_economics gate with economics/approval_steps: it is only
    computed on the КП detail (builder) context, never on list endpoints (N+1 guard)."""
    from rest_framework.test import APIRequestFactory

    request = APIRequestFactory().get("/")
    request.user = CustomUser.objects.create_user(email="v@t.test", username="v@t.test", password="x")
    return QuoteSerializer(quote, context={"request": request, "include_economics": include_economics}).data


@pytest.mark.django_db
def test_fx_market_present_with_uzs_one(quote):
    """fx_market is emitted on the detail (include_economics) context; UZS is anchored at 1."""
    _currency("UZS", is_active=True)

    data = _serialize(quote)

    assert "fx_market" in data
    assert data["fx_market"]["UZS"] == "1"


@pytest.mark.django_db
def test_fx_market_uses_latest_table_rate(quote):
    """A known currency reports the latest rate_to_uzs from the local ExchangeRate table."""
    _currency("UZS", is_active=True)
    usd = _currency("USD", is_active=True)
    ExchangeRate.objects.filter(currency=usd).delete()
    # Two rows — the map must reflect the most recent rate_date, not the stale one.
    ExchangeRate.objects.create(
        currency=usd, rate_date=datetime.date(2026, 1, 1), rate_to_uzs=Decimal("11000.00"), source="TEST"
    )
    ExchangeRate.objects.create(
        currency=usd, rate_date=datetime.date(2026, 7, 1), rate_to_uzs=Decimal("12500.75"), source="TEST"
    )

    data = _serialize(quote)

    # rate_to_uzs is DecimalField(decimal_places=6) → the string carries its stored scale,
    # the SAME shape fx_snapshot freezes (str(Decimal)), which the frontend mirror parses.
    assert Decimal(data["fx_market"]["USD"]) == Decimal("12500.75")
    assert data["fx_market"]["USD"] == "12500.750000"


@pytest.mark.django_db
def test_fx_market_omits_currency_without_rate(quote):
    """A currency with no ExchangeRate row is ABSENT — the mirror keeps its honest «no rate» marker."""
    _currency("UZS", is_active=True)
    eur = _currency("EUR", is_active=True)
    ExchangeRate.objects.filter(currency=eur).delete()  # ensure genuinely no rate

    data = _serialize(quote)

    assert "EUR" not in data["fx_market"]
    # sanity: the map is not simply empty — UZS is still there.
    assert data["fx_market"]["UZS"] == "1"


@pytest.mark.django_db
def test_fx_market_excludes_inactive_currency(quote):
    """Only ACTIVE currencies appear — an inactive lookup row is never offered."""
    _currency("UZS", is_active=True)
    gbp = _currency("GBP", is_active=False)
    ExchangeRate.objects.filter(currency=gbp).delete()
    ExchangeRate.objects.create(
        currency=gbp, rate_date=datetime.date(2026, 7, 1), rate_to_uzs=Decimal("15000.00"), source="TEST"
    )

    data = _serialize(quote)

    assert "GBP" not in data["fx_market"]


@pytest.mark.django_db
def test_fx_market_gated_off_without_include_economics(quote):
    """Without include_economics (LIST endpoints — deals list nests active_quote) fx_market is {}
    and costs ZERO ExchangeRate queries: adversarial-review MAJOR — 5 queries × every deal row."""
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    _currency("UZS", is_active=True)
    usd = _currency("USD", is_active=True)
    ExchangeRate.objects.create(
        currency=usd, rate_date=datetime.date(2026, 7, 1), rate_to_uzs=Decimal("12500.75"), source="TEST"
    )

    with CaptureQueriesContext(connection) as captured:
        data = _serialize(quote, include_economics=False)

    assert data["fx_market"] == {}
    assert not any("exchangerate" in query["sql"].lower() for query in captured.captured_queries)
