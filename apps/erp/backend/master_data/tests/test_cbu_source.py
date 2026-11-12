"""Источник «ЦБ» (решение владельца 2026-11-11): все валюты ЦБ приходят выключенными с названиями на трёх языках,
курс — по каждой включённой с делением на номинал, правку руками источник не перетирает, пропавшая валюта помечается."""

import datetime
from decimal import Decimal
from unittest import mock

import pytest
from django.core.cache import cache
from finance.services import fx
from rest_framework.test import APIClient

from master_data import cbu
from master_data.models import Currency, ExchangeRate
from master_data.tests.test_lookup_delete_and_archive import operator  # noqa: F401

BASE = "/api/v1/dictionaries"


def _row(code, numeric, ru, uz, en, rate, nominal="1"):
    return {
        "Code": numeric,
        "Ccy": code,
        "CcyNm_RU": ru,
        "CcyNm_UZ": uz,
        "CcyNm_UZC": "",
        "CcyNm_EN": en,
        "Nominal": nominal,
        "Rate": rate,
        "Date": "11.11.2026",
    }


PAYLOAD = [
    _row("USD", "840", "Доллар США", "AQSH dollari", "US Dollar", "12013.52"),
    _row("IDR", "360", "Индонезийская рупия", "Indoneziya rupiyasi", "Indonesian Rupiah", "7.42", nominal="10"),
    _row("KZT", "398", "Казахстанский тенге", "Qozog‘iston tengesi", "Kazakhstan Tenge", "23.10"),
]


class _Resp:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


@pytest.fixture(autouse=True)
def _clean_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def usd():
    row, _ = Currency.objects.update_or_create(
        code="USD", defaults={"name": "Доллар", "is_active": True, "sort_order": 20, "symbol": "$"}
    )
    return row


@pytest.mark.django_db
def test_new_currencies_come_disabled_with_three_names_and_rates_follow_enabled_ones(monkeypatch, usd):
    monkeypatch.setattr("httpx.get", lambda url, **kw: _Resp(PAYLOAD))

    assert fx.fetch_cbu_rates() == 1  # курс только у включённой USD
    idr = Currency.objects.get(code="IDR")
    assert (idr.is_active, idr.name, idr.name_uz, idr.name_en, idr.iso_numeric) == (
        False,
        "Индонезийская рупия",
        "Indoneziya rupiyasi",
        "Indonesian Rupiah",
        "360",
    )
    assert idr.source == "cbu" and idr.synced_at is not None
    usd.refresh_from_db()
    assert (usd.name, usd.iso_numeric, usd.symbol, usd.is_active) == ("Доллар США", "840", "$", True)

    # Владелец включил рупию — со следующего обновления у неё есть курс за одну единицу (номинал ЦБ — 10).
    Currency.objects.filter(code="IDR").update(is_active=True)
    assert fx.fetch_cbu_rates() == 2
    rate = ExchangeRate.objects.get(currency__code="IDR")
    assert rate.rate_to_uzs == Decimal("0.742") and rate.rate_date == datetime.date(2026, 11, 11)
    assert fx.is_tracked("IDR") and not fx.is_tracked("KZT") and not fx.is_tracked("UZS")


@pytest.mark.django_db
def test_name_changed_by_hand_is_kept_and_other_fields_still_follow_the_source(operator, usd):  # noqa: F811
    cbu.sync_currencies(cbu.parse(PAYLOAD))
    api = APIClient()
    api.force_authenticate(user=operator)
    changed = api.patch(f"{BASE}/currencies/USD", {"name": {"ru": "Доллар"}}, format="json")
    assert changed.status_code == 200, changed.content
    assert changed.json()["source"]["name"]["ru"] == "ЦБ"
    usd.refresh_from_db()
    assert usd.manual_fields == ["name"]

    renamed = [{**PAYLOAD[0], "CcyNm_RU": "Доллар США (новое)", "CcyNm_EN": "United States Dollar"}]
    cbu.sync_currencies(cbu.parse(renamed))
    usd.refresh_from_db()
    assert (usd.name, usd.name_en) == ("Доллар", "United States Dollar")


@pytest.mark.django_db
def test_missing_currency_is_marked_only_when_the_answer_is_complete(usd):
    cbu.sync_currencies(cbu.parse(PAYLOAD))
    short = cbu.sync_currencies(cbu.parse(PAYLOAD[:1]))
    assert short.missing == 0  # ответ из одной строки — сбой источника, пропавших не помечаем
    assert Currency.objects.get(code="KZT").in_source

    full = [PAYLOAD[0]] + [_row(f"X{i:02d}", f"{i:03d}", f"Валюта {i}", "", "", "1") for i in range(cbu.MIN_CURRENCIES)]
    summary = cbu.sync_currencies(cbu.parse(full))
    assert summary.missing == 2
    kzt = Currency.objects.get(code="KZT")
    assert not kzt.in_source and Currency.objects.filter(code="KZT").exists()


@pytest.mark.django_db
def test_bad_rows_are_skipped():
    rows = cbu.parse(
        [
            _row("USD", "840", "Доллар США", "", "", "abc"),
            _row("EUR", "978", "Евро", "", "", "13649.76", nominal="0"),
            {"Ccy": ""},
            "junk",
            _row("RUB", "643", "Российский рубль", "", "", "150.1"),
        ]
    )
    assert [r.code for r in rows] == ["RUB"]


@pytest.mark.django_db
def test_catalog_and_rows_show_the_source_and_refresh_queues_the_job(operator, usd):  # noqa: F811
    cbu.sync_currencies(cbu.parse(PAYLOAD))
    api = APIClient()
    api.force_authenticate(user=operator)
    kinds = {d["kind"]: d for d in api.get(BASE).json()["items"]}
    assert kinds["currencies"]["source"]["name"] == {"ru": "ЦБ", "uz": "MB", "en": "CBU"}
    assert kinds["currencies"]["source"]["synced_at"]
    assert kinds["units"]["source"] is None
    rows = {r["code"]: r for r in api.get(f"{BASE}/currencies", {"include_hidden": "true"}).json()["items"]}
    assert rows["KZT"]["source"]["missing"] is False and rows["KZT"]["active"] is False

    with mock.patch("master_data.tasks.refresh_exchange_rates.delay") as delay:
        queued = api.post(f"{BASE}/currencies/sync")
        assert (queued.status_code, queued.json()) == (202, {"queued": True})
        delay.assert_called_once_with()
        assert api.post(f"{BASE}/units/sync").status_code == 404
