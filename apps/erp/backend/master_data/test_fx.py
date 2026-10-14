"""FX foundation: CBU fetch upsert + UZS conversion (manual override wins)."""

import datetime
from decimal import Decimal

import pytest

from master_data import fx
from master_data.models import Currency, ExchangeRate

pytestmark = pytest.mark.django_db


class _FakeResp:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


def test_fetch_cbu_rates_upserts_tracked_only_and_is_idempotent(monkeypatch):
    Currency.objects.get_or_create(code="USD", defaults={"name": "Доллар", "sort_order": 1})
    Currency.objects.get_or_create(code="EUR", defaults={"name": "Евро", "sort_order": 2})
    payload = [
        {"Ccy": "USD", "Rate": "12013.52", "Date": "26.06.2026"},
        {"Ccy": "EUR", "Rate": "13649.76", "Date": "26.06.2026"},
        {"Ccy": "XYZ", "Rate": "1.0", "Date": "26.06.2026"},  # untracked → ignored
    ]
    monkeypatch.setattr("httpx.get", lambda url, **kw: _FakeResp(payload))

    assert fx.fetch_cbu_rates() == 2  # USD + EUR only
    usd = ExchangeRate.objects.get(currency__code="USD")
    assert usd.rate_to_uzs == Decimal("12013.52")
    assert usd.rate_date == datetime.date(2026, 6, 26)
    assert usd.source == "CBU"
    # running again upserts (no duplicate rows for the same currency+date)
    fx.fetch_cbu_rates()
    assert ExchangeRate.objects.filter(currency__code="USD").count() == 1


def test_rate_lookup_and_conversion_with_manual_override():
    usd = Currency.objects.get_or_create(code="USD", defaults={"name": "$", "sort_order": 1})[0]
    from django.utils import timezone

    ExchangeRate.objects.create(currency=usd, rate_to_uzs=Decimal("12000"), rate_date=timezone.localdate())

    assert fx.get_rate_to_uzs("UZS") == Decimal("1")  # base currency
    assert fx.get_rate_to_uzs("USD") == Decimal("12000")
    assert fx.get_rate_to_uzs("ZZZ") is None  # unknown

    assert fx.convert_to_uzs(Decimal("10"), "USD") == Decimal("120000")
    assert fx.convert_to_uzs(Decimal("10"), "USD", rate=Decimal("12100")) == Decimal("121000")  # override wins
    assert fx.convert_to_uzs(Decimal("10"), "ZZZ") is None  # unknown + no override
