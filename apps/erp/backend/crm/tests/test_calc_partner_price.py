"""РАСЧ-1: закупка строки расчёта берёт цену партнёра, клиентская цена — закупка + наценка по умолчанию.

Правило: самая низкая действующая цена партнёра (сравнение по курсу), цена в валюте строки после перевода; истёкшая
цена молча не берётся — «запросить цену»; другую цену из короткого списка выбирает человек; закупку, введённую руками,
источник не подписывает.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from accounts.models import Company, CompanyType
from catalog.models import Product, SupplierOffer
from core.models import ExchangeRate
from crm.models import Quote, QuoteItem
from crm.tests.test_calc import _api, _url
from crm.tests.test_calc import world as calc_world  # noqa: F401  (фикстура world для этого модуля)
from master_data.models import Currency

pytestmark = pytest.mark.django_db

TODAY = timezone.localdate()


def _vendor(name, inn):
    vendor = Company.objects.create(name=name, inn=inn)
    vendor.types.add(CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier"})[0])
    return vendor


@pytest.fixture
def prices(calc_world):  # noqa: F811
    world = calc_world
    usd = Currency.objects.get_or_create(code="USD", defaults={"name": "Доллар", "sort_order": 20})[0]
    uzs = Currency.objects.get(code="UZS")
    ExchangeRate.objects.create(currency=usd, rate_to_uzs=Decimal("12000"), rate_date=TODAY, source="CBU")
    product = Product.objects.create(name="Крепление рельсовое КБ-65", manufacturer_part_number="КБ-65")
    a, b, c = (_vendor(f"ООО Партнёр {n}", f"770000030{n}") for n in "123")
    # A: 100 млн сум; B: 7000 USD = 84 млн сум (дешевле, чужая валюта); C: 50 млн, но срок истёк.
    SupplierOffer.objects.create(product=product, supplier=a, base_price=Decimal("100000000"), currency=uzs)
    SupplierOffer.objects.create(
        product=product, supplier=b, base_price=Decimal("7000"), currency=usd, valid_until=TODAY + timedelta(days=30)
    )
    SupplierOffer.objects.create(
        product=product, supplier=c, base_price=Decimal("50000000"), currency=uzs, valid_until=TODAY - timedelta(days=1)
    )
    return {**world, "product": product, "usd": usd, "uzs": uzs, "a": a, "b": b, "c": c}


def _add(world, **row):
    _api(world["supply"]).post(_url(world, "start/"))
    response = _api(world["supply"]).post(_url(world, "lines/"), {"lines": [row]}, format="json")
    assert response.status_code == 201, response.json()
    return response.json()["lines"][-1]


def test_cheapest_valid_price_wins_in_its_own_currency_and_expired_is_ignored(prices):
    line = _add(prices, product_id=prices["product"].pk, quantity=2)
    assert line["purchase_price"] == "7000.00" and line["purchase_currency"] == "USD"
    source = line["partner_price"]["source"]
    assert source["supplier"] == "ООО Партнёр 2" and source["freshness"] == "ok"
    assert source["valid_until"] == (TODAY + timedelta(days=30)).isoformat()
    options = line["partner_price"]["options"]
    assert [o["supplier"] for o in options] == ["ООО Партнёр 2", "ООО Партнёр 1"], "истёкшая цена не в списке"
    assert line["partner_price"]["can_request"] is False and line["partner_price"]["expired"] is None


def test_price_is_converted_to_the_quote_cost_currency(prices):
    _api(prices["supply"]).post(_url(prices, "start/"))
    Quote.objects.filter(deal=prices["deal"]).update(cost_currency_default=prices["uzs"])
    line = _add(prices, product_id=prices["product"].pk)
    assert line["purchase_price"] == "84000000.00" and line["purchase_currency"] == "UZS"
    assert line["partner_price"]["source"]["price"] == "84000000.00"


def test_only_expired_price_is_never_used_silently(prices):
    SupplierOffer.objects.filter(supplier__in=[prices["a"], prices["b"]]).delete()
    line = _add(prices, product_id=prices["product"].pk)
    assert line["purchase_price"] == "0.00"
    part = line["partner_price"]
    assert part["source"] is None and part["options"] == [] and part["can_request"] is True
    assert part["expired"] == {"supplier": "ООО Партнёр 3", "valid_until": (TODAY - timedelta(days=1)).isoformat()}


def test_price_without_exchange_rate_is_skipped_not_guessed(prices):
    ExchangeRate.objects.all().delete()
    line = _add(prices, product_id=prices["product"].pk)
    assert line["purchase_price"] == "100000000.00" and line["purchase_currency"] == "UZS"
    assert [o["supplier"] for o in line["partner_price"]["options"]] == ["ООО Партнёр 1"]


def test_line_matched_to_catalog_card_later_gets_the_partner_price(prices):
    line = _add(prices, name="Крепление для рельса", quantity=1)
    assert line["purchase_price"] == "0.00" and line["partner_price"]["can_request"] is True
    response = _api(prices["supply"]).patch(
        _url(prices, f"lines/{line['id']}/"), {"product_id": prices["product"].pk}, format="json"
    )
    assert response.status_code == 200, response.json()
    matched = next(entry for entry in response.json()["lines"] if entry["id"] == line["id"])
    assert matched["purchase_price"] == "7000.00" and matched["partner_price"]["source"]["supplier"] == "ООО Партнёр 2"


def test_user_picks_another_partner_and_expired_one_is_refused(prices):
    line = _add(prices, product_id=prices["product"].pk)
    other = next(o for o in line["partner_price"]["options"] if not o["chosen"])
    response = _api(prices["supply"]).patch(
        _url(prices, f"lines/{line['id']}/"), {"offer_id": other["offer_id"]}, format="json"
    )
    assert response.status_code == 200, response.json()
    picked = next(entry for entry in response.json()["lines"] if entry["id"] == line["id"])
    assert picked["purchase_price"] == "8333.33" and picked["partner_price"]["source"]["supplier"] == "ООО Партнёр 1"
    expired = SupplierOffer.objects.get(supplier=prices["c"])
    denied = _api(prices["supply"]).patch(_url(prices, f"lines/{line['id']}/"), {"offer_id": expired.pk}, format="json")
    assert denied.status_code == 409 and denied.json()["detail"] == "OFFER_NOT_AVAILABLE"


def test_manual_purchase_price_drops_the_partner_source(prices):
    line = _add(prices, product_id=prices["product"].pk)
    response = _api(prices["supply"]).patch(
        _url(prices, f"lines/{line['id']}/"), {"purchase_price": "6500"}, format="json"
    )
    edited = next(entry for entry in response.json()["lines"] if entry["id"] == line["id"])
    assert edited["purchase_price"] == "6500.00" and edited["partner_price"]["source"] is None


def test_client_price_is_purchase_plus_default_margin(prices):
    line = _add(prices, product_id=prices["product"].pk)
    quote = Quote.objects.get(deal=prices["deal"])
    assert quote.margin_percent == Decimal("20.00"), "наценка по умолчанию из настроек «Продажи»"
    item = QuoteItem.objects.get(pk=line["id"])
    assert item.final_price_excl_vat == (item.landed_cost * Decimal("1.2")).quantize(Decimal("0.01"))
    assert Decimal(line["client_price"]) > Decimal(line["cost"])
    assert line["markup_pct"] == "20.0"


def test_configured_default_margin_is_used(prices):
    settings_row = prices["seller"].settings
    settings_row.default_margin_percent = Decimal("12.50")
    settings_row.save()
    _add(prices, product_id=prices["product"].pk)
    assert Quote.objects.get(deal=prices["deal"]).margin_percent == Decimal("12.50")


def test_delivery_term_is_taken_from_the_chosen_partner_price(prices):
    SupplierOffer.objects.filter(supplier=prices["b"]).update(order_lead_time_days=14, in_stock_lead_time_days=0)
    line = _add(prices, product_id=prices["product"].pk)
    assert line["partner_price"]["source"]["supplier"] == "ООО Партнёр 2"
    assert line["lead_days"] == 14


def test_margin_below_threshold_is_flagged_on_line_and_totals_but_does_not_block(prices):
    settings_row = prices["seller"].settings
    settings_row.default_margin_percent = Decimal("3.20")
    settings_row.min_margin_percent = Decimal("12.00")
    settings_row.save()
    line = _add(prices, product_id=prices["product"].pk)
    assert line["margin_below"] is True and line["margin_pct"] == "3.1", "маржа на цену, не наценка на себестоимость"
    assert line["markup_pct"] == "3.2"
    sheet = _api(prices["supply"]).get(_url(prices, "")).json()
    assert sheet["totals"]["margin_below"] is True and sheet["totals"]["threshold_pct"] == "15.0", "порог — из задания резолюции"
    assert sheet["ready"]["blocker"] != "margin_below", "предупреждение не запрещает «Расчёт готов»"


def test_margin_at_default_is_not_flagged(prices):
    settings_row = prices["seller"].settings
    settings_row.default_margin_percent = Decimal("30.00")
    settings_row.min_margin_percent = Decimal("12.00")
    settings_row.save()
    line = _add(prices, product_id=prices["product"].pk)
    assert line["margin_below"] is False


def test_cheapest_supplier_is_compared_in_soums_not_by_the_raw_number(prices):
    """7 000 USD (84 млн сум) числом меньше 50 млн сум, но дороже: строка и блок поставщика называют одного партнёра и одну цену."""
    SupplierOffer.objects.filter(supplier=prices["c"]).update(valid_until=None)  # 50 млн сум, снова действует
    line = _add(prices, product_id=prices["product"].pk)
    assert line["partner_price"]["source"]["supplier"] == "ООО Партнёр 3"
    assert line["purchase_price"] == "50000000.00" and line["purchase_currency"] == "UZS"
    assert line["supplier"]["name"] == "ООО Партнёр 3"
    assert line["supplier"]["offer_price"] == "50000000.00" and line["supplier"]["offer_currency"] == "UZS"
    # закупка введена руками — источник не подписан, но блок поставщика по-прежнему берёт честно самую низкую цену в сумах
    response = _api(prices["supply"]).patch(
        _url(prices, f"lines/{line['id']}/"), {"purchase_price": "123"}, format="json"
    )
    edited = next(entry for entry in response.json()["lines"] if entry["id"] == line["id"])
    assert edited["supplier"]["name"] == "ООО Партнёр 3"
