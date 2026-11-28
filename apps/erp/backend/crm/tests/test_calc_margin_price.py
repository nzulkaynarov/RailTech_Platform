"""РАСЧ-3: цена клиенту «от маржи» — себестоимость / (1 − маржа), округление вверх, пересчёт сам до отправки КП.

Формула и округление (маржа после округления не ниже заданной), строка «от маржи» у новой строки, пересчёт при любом
входе (закупка, цена партнёра, курс, целевая маржа, шаг), отправленное КП и ручная цена не трогаются, строки до РАСЧ-3
цену не меняют.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.utils import timezone

from catalog.models import SupplierOffer
from core.models import ExchangeRate
from crm.models import CalcLine, CalcPriceBasis, Quote, QuoteItem
from crm.services.quotes.pricing import QuoteCalculationService, margin_price
from crm.tests.test_calc import _api, _url
from crm.tests.test_calc import world as calc_world  # noqa: F401  (фикстура world для prices)
from crm.tests.test_calc_partner_price import _add, prices  # noqa: F401  (фикстура prices)

pytestmark = pytest.mark.django_db

D = Decimal


def _settings(world, **values):
    row = world["seller"].settings
    for key, value in values.items():
        setattr(row, key, D(str(value)))
    row.save()


def _patch(world, line_id, body):
    response = _api(world["supply"]).patch(_url(world, f"lines/{line_id}/"), body, format="json")
    assert response.status_code == 200, response.json()
    return next(entry for entry in response.json()["lines"] if entry["id"] == line_id)


def _line(world, line_id):
    sheet = _api(world["supply"]).get(_url(world, "")).json()
    return next(entry for entry in sheet["lines"] if entry["id"] == line_id)


# ── формула и округление ─────────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("cost", "margin", "step", "expected"),
    [
        ("84000000", "20", "1000", "105000000.00"),  # ровно делится
        ("1234567", "20", "1000", "1544000.00"),  # 1 543 208,75 → вверх до шага
        ("1234567", "20", "0", "1543209.00"),  # без шага: вверх до целого сума
        ("1000", "25", "1000", "2000.00"),  # 1 333,33 → шаг 1 000
        ("0", "20", "1000", "0.00"),  # нет себестоимости — нет цены
    ],
)
def test_price_is_cost_over_one_minus_margin_rounded_up(cost, margin, step, expected):
    assert margin_price(D(cost), D(margin), D("0"), D(step), D("1")) == D(expected)


def test_margin_after_rounding_is_never_below_target():
    for cost in (1, 7, 999, 12_345, 1_234_567, 98_765_431, 3_333_333_333):
        for margin in (D("5"), D("15"), D("20"), D("33.3"), D("50")):
            for step in (D("0"), D("1000"), D("50000")):
                price = margin_price(D(cost), margin, D("0"), step, D("1"))
                assert (price - D(cost)) / price * 100 >= margin - D("0.0000001"), (cost, margin, step)
                assert step == 0 or price % step == 0 or price < step


def test_foreign_currency_price_rounds_up_to_cents_only():
    assert margin_price(D("100"), D("20"), D("0"), D("0"), D("0.01")) == D("125.00")
    assert margin_price(D("100.10"), D("20"), D("0"), D("0"), D("0.01")) == D("125.13")


# ── новая строка и настройки ─────────────────────────────────────────────────────────────────────────────────────


def test_new_line_is_margin_priced_from_the_company_target_and_step(prices):  # noqa: F811
    _settings(prices, target_margin_percent=20, price_rounding_step=1000)
    line = _add(prices, product_id=prices["product"].pk)  # 7000 USD × 12 000 = 84 000 000 сум
    assert line["cost"] == "84000000.00"
    assert line["price_mode"] == "margin" and line["margin_target_pct"] == "20.0"
    assert line["client_price"] == "105000000.00" and line["margin_pct"] == "20.0"
    totals = _api(prices["supply"]).get(_url(prices, "")).json()["totals"]
    assert totals["target_pct"] == "20.0" and totals["rounding_step"] == "1000"


def test_rounding_step_is_applied_and_zero_switches_it_off(prices, django_capture_on_commit_callbacks):  # noqa: F811
    _settings(prices, target_margin_percent=20, price_rounding_step=1000)
    line = _add(prices, product_id=prices["product"].pk)
    edited = _patch(prices, line["id"], {"purchase_price": "1234567", "purchase_currency": "UZS"})
    assert edited["client_price"] == "1544000.00"
    assert Decimal(edited["margin_pct"]) >= D("20.0")
    with django_capture_on_commit_callbacks(execute=True):
        _settings(prices, price_rounding_step=0)
    assert _line(prices, line["id"])["client_price"] == "1543209.00"


def test_default_markup_setting_no_longer_drives_new_prices(prices):  # noqa: F811
    _settings(prices, default_margin_percent=99, target_margin_percent=20)
    line = _add(prices, product_id=prices["product"].pk)
    assert line["client_price"] == "105000000.00"


# ── пересчёт при любом изменении ────────────────────────────────────────────────────────────────────────────────


def test_price_follows_purchase_quantity_free_and_partner_choice(prices):  # noqa: F811
    _settings(prices, target_margin_percent=20)
    line = _add(prices, product_id=prices["product"].pk)
    assert line["client_price"] == "105000000.00"
    same = _patch(prices, line["id"], {"quantity": 3})
    assert same["client_price"] == "105000000.00", "количество цену за единицу не меняет"
    other = next(o for o in line["partner_price"]["options"] if not o["chosen"])  # Партнёр 1: 100 млн сум
    picked = _patch(prices, line["id"], {"offer_id": other["offer_id"]})
    assert picked["client_price"] == "125000000.00", "выбор цены партнёра пересчитал цену"
    changed = _patch(prices, line["id"], {"purchase_price": "8000000", "purchase_currency": "UZS"})
    assert changed["client_price"] == "10000000.00"


def test_exchange_rate_refresh_reprices_live_draft_lines(prices, django_capture_on_commit_callbacks):  # noqa: F811
    _settings(prices, target_margin_percent=20)
    line = _add(prices, product_id=prices["product"].pk)
    assert line["client_price"] == "105000000.00"
    with django_capture_on_commit_callbacks(execute=True):
        ExchangeRate.objects.filter(currency=prices["usd"]).update(rate_to_uzs=D("12600"))
        ExchangeRate.objects.get(currency=prices["usd"]).save()  # запись курса (ЦБ или вручную) → пересчёт
    again = _line(prices, line["id"])
    assert again["cost"] == "88200000.00" and again["client_price"] == "110250000.00"


def test_target_margin_change_reprices_drafts_but_not_sent_quote(prices, django_capture_on_commit_callbacks):  # noqa: F811
    _settings(prices, target_margin_percent=20)
    line = _add(prices, product_id=prices["product"].pk)
    with django_capture_on_commit_callbacks(execute=True):
        _settings(prices, target_margin_percent=30)
    assert _line(prices, line["id"])["client_price"] == "120000000.00"
    Quote.objects.filter(deal=prices["deal"]).update(frozen_at=timezone.now())
    with django_capture_on_commit_callbacks(execute=True):
        _settings(prices, target_margin_percent=50)
        ExchangeRate.objects.get(currency=prices["usd"]).save()
    item = QuoteItem.objects.get(pk=line["id"])
    QuoteCalculationService.recalculate_quote(item.quote_id)
    item.refresh_from_db()
    assert item.final_price_excl_vat == D("120000000.00"), "отправленное КП цену не меняет"


def test_quote_off_draft_keeps_its_prices(prices):  # noqa: F811
    from crm.constants import QuoteStatusCode
    from crm.models import QuoteStatus

    _settings(prices, target_margin_percent=20)
    line = _add(prices, product_id=prices["product"].pk)
    QuoteStatus.objects.get_or_create(code=QuoteStatusCode.SENT, defaults={"name": "Sent", "sort_order": 50})
    Quote.objects.filter(deal=prices["deal"]).update(status=QuoteStatus.objects.get(code=QuoteStatusCode.SENT))
    _settings(prices, target_margin_percent=40)
    quote = Quote.objects.get(deal=prices["deal"])
    QuoteCalculationService.recalculate_quote(quote.pk)
    assert QuoteItem.objects.get(pk=line["id"]).final_price_excl_vat == D("105000000.00")


# ── ручная цена и маржа строки ──────────────────────────────────────────────────────────────────────────────────


def test_typed_price_is_manual_never_recalculated_and_can_return_to_margin(prices, django_capture_on_commit_callbacks):  # noqa: F811
    _settings(prices, target_margin_percent=20)
    line = _add(prices, product_id=prices["product"].pk)
    manual = _patch(prices, line["id"], {"client_price": "99000000"})
    assert manual["price_mode"] == "manual" and manual["client_price"] == "99000000.00"
    assert manual["margin_target_pct"] == "20.0", "«вернуть N %»"
    moved = _patch(prices, line["id"], {"purchase_price": "7500"})  # закупка выросла
    assert moved["client_price"] == "99000000.00" and moved["price_mode"] == "manual"
    with django_capture_on_commit_callbacks(execute=True):
        _settings(prices, target_margin_percent=35)
    assert _line(prices, line["id"])["client_price"] == "99000000.00"
    back = _patch(prices, line["id"], {"price_mode": "margin"})
    assert back["price_mode"] == "margin" and back["margin_target_pct"] == "35.0"
    assert Decimal(back["margin_pct"]) >= D("35.0")
    assert QuoteItem.objects.get(pk=line["id"]).client_price_fixed is None


def test_line_margin_stays_margin_based_and_follows_cost(prices):  # noqa: F811
    _settings(prices, target_margin_percent=20)
    line = _add(prices, product_id=prices["product"].pk)
    own = _patch(prices, line["id"], {"margin_pct": "30"})
    assert own["price_mode"] == "margin" and own["margin_target_pct"] == "30.0"
    assert own["client_price"] == "120000000.00"
    after = _patch(prices, line["id"], {"purchase_price": "8000000", "purchase_currency": "UZS"})
    assert after["client_price"] == "11429000.00", "цена следует за закупкой с той же маржой строки"
    assert CalcLine.objects.get(item_id=line["id"]).margin_percent == D("30.00")


def test_price_inputs_exclude_each_other_and_margin_is_bounded(prices):  # noqa: F811
    line = _add(prices, product_id=prices["product"].pk)
    url = _url(prices, f"lines/{line['id']}/")
    both = _api(prices["supply"]).patch(url, {"client_price": "1000", "margin_pct": "20"}, format="json")
    assert both.status_code == 400
    too_high = _api(prices["supply"]).patch(url, {"margin_pct": "99"}, format="json")
    assert too_high.status_code == 400


# ── строки до РАСЧ-3 ────────────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("basis", ["", CalcPriceBasis.MARKUP, CalcPriceBasis.CLIENT])
def test_lines_before_rasch3_keep_their_prices(prices, django_capture_on_commit_callbacks, basis):  # noqa: F811
    _settings(prices, target_margin_percent=20)
    line = _add(prices, product_id=prices["product"].pk)
    item = QuoteItem.objects.get(pk=line["id"])
    CalcLine.objects.filter(item=item).update(price_basis=basis)
    Quote.objects.filter(pk=item.quote_id).update(margin_percent=D("20.00"))
    if basis == CalcPriceBasis.CLIENT:
        QuoteItem.objects.filter(pk=item.pk).update(client_price_fixed=D("101000000"))
    QuoteCalculationService.recalculate_quote(item.quote_id)
    before = QuoteItem.objects.get(pk=item.pk).final_price_excl_vat
    with django_capture_on_commit_callbacks(execute=True):
        _settings(prices, target_margin_percent=60, price_rounding_step=5000)
        ExchangeRate.objects.get(currency=prices["usd"]).save()
    QuoteCalculationService.recalculate_quote(item.quote_id)
    after = QuoteItem.objects.get(pk=item.pk)
    assert after.final_price_excl_vat == before, "строка до РАСЧ-3 цену сама не меняет"
    assert _line(prices, item.pk)["price_mode"] in ("legacy", "manual")


def test_rounding_step_setting_is_validated(prices):  # noqa: F811
    from accounts.services.company_settings import update_company_settings

    owner = prices["supply"]
    bad = update_company_settings(owner, prices["seller"], {"price_rounding_step": "-5"})
    assert bad[1] in ("BAD_NUMBER", "NOT_COMPANY_OWNER")
    none = update_company_settings(owner, prices["seller"], {"price_rounding_step": None})
    assert none[1] in ("BAD_NUMBER", "NOT_COMPANY_OWNER")
