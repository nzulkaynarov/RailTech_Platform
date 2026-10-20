"""M1-ERP-08: отклонение маржи при фактической закупке — таблица расчёта, сервис, эндпоинты, журнал."""

from decimal import Decimal

import pytest
from finance.models import DealPurchaseActual
from finance.services.margin_deviation import (
    actual_cost_in_base,
    compute_margin_deviation,
    margin_summary,
    reference_quote,
)
from rest_framework.test import APIClient
from sales.tests.helpers_fx import build_quote, build_world, send_quote, set_rate

from crm.models import ActivityLog, QuoteStatus

pytestmark = pytest.mark.django_db
D = Decimal


# ── 1. Таблица расчёта (чистые функции) ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "revenue, quoted_cost, actual_cost, quoted_pct, actual_pct, deviation, points, relative",
    [
        ("1000", "800", "800", "20.00", "20.00", "0.00", "0.00", "0.00"),  # без изменений
        ("1000", "800", "850", "20.00", "15.00", "-50.00", "-5.00", "-25.00"),  # закупка дороже
        ("1000", "800", "760", "20.00", "24.00", "40.00", "4.00", "20.00"),  # закупка дешевле
        ("1000", "1000", "1050", "0.00", "-5.00", "-50.00", "-5.00", None),  # нулевая маржа в КП
        ("1000", "1000", "1000", "0.00", "0.00", "0.00", "0.00", None),  # ноль к нулю
        ("3", "1", "1.01", "66.67", "66.33", "-0.01", "-0.33", "-0.50"),  # округление процентов
        ("0", "0", "0", "0.00", "0.00", "0.00", "0.00", None),  # пустое КП
    ],
    ids=["same", "cost-up", "cost-down", "zero-margin", "zero-zero", "rounding", "empty"],
)
def test_margin_summary_table(revenue, quoted_cost, actual_cost, quoted_pct, actual_pct, deviation, points, relative):
    result = margin_summary(D(revenue), D(quoted_cost), D(actual_cost))
    assert result["quoted_margin_percent"] == D(quoted_pct)
    assert result["actual_margin_percent"] == D(actual_pct)
    assert result["deviation_amount"] == D(deviation)
    assert result["deviation_percent_points"] == D(points)
    assert result["deviation_profit_percent"] == (D(relative) if relative is not None else None)
    assert result["actual_profit"] - result["quoted_profit"] == result["deviation_amount"]


@pytest.mark.parametrize(
    "actual_amount, actual_rate, expected",
    [
        (None, None, "12650000.00"),  # факта нет — как в КП
        (None, "12900", "12900000.00"),  # курс вырос
        (None, "12500", "12500000.00"),  # курс упал
        ("1050", "12650", "13282500.00"),  # закупка дороже по тому же курсу
        ("950", "12900", "12255000.00"),  # дешевле, но курс выше
        ("333.33", "12650.55", "4216807.83"),  # округление до копейки 0.5 вверх
        ("0", "12650", "0.00"),  # закупка бесплатно
    ],
    ids=["no-actual", "rate-up", "rate-down", "cost-up", "cost-down-rate-up", "rounding", "free"],
)
def test_actual_cost_in_base_table(actual_amount, actual_rate, expected):
    quoted_amount, quoted_cost = D("1000"), D("12650000.00")
    result = actual_cost_in_base(
        quoted_amount,
        quoted_cost,
        D(actual_amount) if actual_amount is not None else None,
        D(actual_rate) if actual_rate is not None else None,
    )
    assert result == D(expected)


# ── 2. Сервис над сделкой ───────────────────────────────────────────────────────────────────


@pytest.fixture
def world(db):
    return build_world()


@pytest.fixture
def sent(world):
    """Отправленное КП: 10 × 100 USD по 12 650 + 2 000 000 UZS, наценка 20 %."""
    set_rate("USD", "12650")
    quote = build_quote(world, [("100", "USD", 10), ("1000000", "UZS", 2)], margin="20", vat="12")
    send_quote(world, quote)
    quote.refresh_from_db()
    return quote


def _api(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


def _url(world, suffix):
    return f"/api/v1/finance/deals/{world.deal.pk}/{suffix}"


def test_no_reference_quote_before_send(world):
    set_rate("USD", "12650")
    build_quote(world, [("100", "USD", 1)])
    data = compute_margin_deviation(world.deal)
    assert data["reference_quote"] is None and data["rows"] == []


def test_deviation_without_actuals_is_zero(world, sent):
    data = compute_margin_deviation(world.deal)
    # Выручка = (12 650 000 + 2 000 000) × 1.2 = 17 580 000; себестоимость 14 650 000.
    assert data["revenue"] == D("17580000.00")
    assert data["quoted_cost"] == data["actual_cost"] == D("14650000.00")
    assert data["quoted_margin_percent"] == D("16.67")
    assert data["deviation_amount"] == D("0.00") and data["has_actuals"] is False
    usd = next(row for row in data["rows"] if row["currency"] == "USD")
    assert (usd["quoted_amount"], usd["quoted_rate"], usd["quoted_cost"]) == (D("1000.00"), "12650", D("12650000.00"))


@pytest.mark.parametrize(
    "amount, rate, deviation, actual_pct",
    [
        (None, "12900", "-250000.00", "15.24"),  # курс вырос — маржа упала, цена клиенту та же
        (None, "12400", "250000.00", "18.09"),  # курс упал — маржа выросла
        ("1100", "12650", "-1265000.00", "9.47"),  # закупка дороже
    ],
    ids=["rate-up", "rate-down", "cost-up"],
)
def test_deviation_by_actual_purchase(world, sent, amount, rate, deviation, actual_pct):
    from finance.services.margin_deviation import PurchaseActualInput, record_purchase_actual

    record_purchase_actual(world.deal, actor=world.finance, data=PurchaseActualInput("USD", amount, rate))
    data = compute_margin_deviation(world.deal)
    assert data["deviation_amount"] == D(deviation)
    assert data["actual_margin_percent"] == D(actual_pct)
    assert data["revenue"] == D("17580000.00")  # цена клиенту не пересчитывается
    sent.refresh_from_db()
    assert sent.total_incl_vat == D("19689600.00")


# ── 2a. Одна точность: сумма по строкам против суммы по строкам (FIX-41, F-13) ─────────────


def _line_cost(base, duty, rate):
    """Себестоимость единицы в сумах так, как её считает движок КП: округление до копейки на строке."""
    return ((D(base) + D(duty)) * D(rate)).quantize(D("0.01"), rounding="ROUND_HALF_UP")


PENNY_CASES = [
    pytest.param([("0.10", "USD", 3)], "12650.55", id="tenth-x3"),
    pytest.param([("0.33", "USD", 7)], "12650.55", id="third-x7"),
    pytest.param([("0.10", "USD", 3), ("0.35", "USD", 3)], "12650.55", id="two-lines"),
    pytest.param([("1.01", "USD", 3, "0.05")], "7.777777", id="duty-six-digit-rate"),
    pytest.param([("0.01", "USD", 1)], "50.5", id="half-penny-up"),
    pytest.param([("19.99", "USD", 13)], "12713.123456", id="many-units"),
    pytest.param([("0.07", "USD", 11), ("0.13", "USD", 17), ("2.49", "USD", 5)], "12345.678901", id="three-lines"),
]


def _quoted_amount(lines):
    return sum(((D(line[0]) + D(line[3] if len(line) > 3 else "0")) * line[2] for line in lines), D("0"))


@pytest.mark.parametrize("explicit_amount", [False, True], ids=["amount-as-quoted", "amount-explicit"])
@pytest.mark.parametrize("lines, rate", PENNY_CASES)
def test_actual_equal_to_quote_has_no_phantom_deviation(world, lines, rate, explicit_amount):
    """Закупка по тому же курсу и на ту же сумму — отклонение ровно 0, а не «−0,01» от разного округления."""
    from finance.services.margin_deviation import PurchaseActualInput, record_purchase_actual

    set_rate("USD", rate)
    quote = build_quote(world, lines, margin="20")
    send_quote(world, quote)
    amount = _quoted_amount(lines) if explicit_amount else None

    record_purchase_actual(world.deal, actor=world.finance, data=PurchaseActualInput("USD", amount, rate))
    data = compute_margin_deviation(world.deal)

    assert data["has_actuals"] is True
    assert data["actual_cost"] == data["quoted_cost"]
    assert data["deviation_amount"] == D("0.00")
    assert data["deviation_percent_points"] == D("0.00")
    assert data["rows"][0]["cost_deviation"] == D("0.00")


@pytest.mark.parametrize("lines, rate", PENNY_CASES)
def test_rate_change_deviation_is_sum_of_line_differences(world, lines, rate):
    """Курс закупки отличается — отклонение равно сумме разниц по строкам, каждая округлена как в КП."""
    from finance.services.margin_deviation import PurchaseActualInput, record_purchase_actual

    set_rate("USD", rate)
    quote = build_quote(world, lines, margin="20")
    send_quote(world, quote)
    new_rate = str(D(rate) + D("17.123456"))

    record_purchase_actual(world.deal, actor=world.finance, data=PurchaseActualInput("USD", None, new_rate))
    data = compute_margin_deviation(world.deal)

    expected = sum(
        (
            (
                _line_cost(line[0], line[3] if len(line) > 3 else "0", new_rate)
                - _line_cost(line[0], line[3] if len(line) > 3 else "0", rate)
            )
            * line[2]
            for line in lines
        ),
        D("0"),
    )
    assert data["deviation_amount"] == -expected
    assert data["actual_cost"] - data["quoted_cost"] == expected


def test_total_cost_matches_quote_economics_to_the_penny(world):
    """Себестоимость и прибыль в отклонении совпадают с «Экономикой сделки» КП до копейки."""
    from crm.services.quotes import compute_quote_economics

    set_rate("USD", "12650.55")
    set_rate("EUR", "13800.45")
    quote = build_quote(world, [("0.10", "USD", 3), ("0.35", "EUR", 3), ("1000", "UZS", 1)], margin="20")
    send_quote(world, quote)
    quote.refresh_from_db()

    economics = compute_quote_economics(quote)
    data = compute_margin_deviation(world.deal)

    assert data["quoted_cost"] == economics["total_landed_cost"]
    assert data["quoted_profit"] == economics["gross_profit"]


def test_partial_actual_scales_line_cost_in_one_precision(world):
    """Фактическая сумма вдвое меньше КП по тому же курсу — себестоимость ровно вдвое меньше без «копеек»."""
    from finance.services.margin_deviation import PurchaseActualInput, record_purchase_actual

    set_rate("USD", "12650.55")
    lines = [("0.10", "USD", 4), ("0.30", "USD", 4)]
    send_quote(world, build_quote(world, lines, margin="20"))

    record_purchase_actual(
        world.deal, actor=world.finance, data=PurchaseActualInput("USD", _quoted_amount(lines) / 2, "12650.55")
    )
    data = compute_margin_deviation(world.deal)

    assert data["actual_cost"] * 2 == data["quoted_cost"]


def test_reference_prefers_accepted_quote(world, sent):
    from crm.models import Quote

    later = build_quote(world, [("100", "USD", 1)], version=2)
    Quote.objects.filter(pk=later.pk).update(status=QuoteStatus.objects.get(code="SENT"))
    Quote.objects.filter(pk=later.pk).update(frozen_at=sent.frozen_at)
    assert reference_quote(world.deal).pk == later.pk  # последняя отправленная
    Quote.objects.filter(pk=sent.pk).update(status=QuoteStatus.objects.get(code="APPROVED"))
    assert reference_quote(world.deal).pk == sent.pk  # принятая клиентом важнее


# ── 3. Эндпоинты, права, журнал ─────────────────────────────────────────────────────────────


def test_get_requires_cost_permission(world, sent):
    assert _api(world.fulfillment).get(_url(world, "margin-deviation/")).status_code == 403
    response = _api(world.finance).get(_url(world, "margin-deviation/"))
    assert response.status_code == 200
    assert response.json()["reference_quote"]["id"] == sent.pk
    assert response.json()["quoted_cost"] == "14650000.00"


@pytest.mark.parametrize("who, allowed", [("finance", True), ("supply", True), ("head", True), ("calc", False)])
def test_record_actual_permissions(world, sent, who, allowed):
    response = _api(getattr(world, who)).post(
        _url(world, "purchase-actuals/"), {"currency": "USD", "rate": "12900"}, format="json"
    )
    assert response.status_code == (200 if allowed else 403)
    assert DealPurchaseActual.objects.filter(deal=world.deal).exists() is allowed


def test_record_update_delete_and_journal(world, sent):
    client = _api(world.finance)
    body = {"currency": "usd", "amount": "1020.50", "rate": "12800", "note": "Счёт поставщика №7"}
    data = client.post(_url(world, "purchase-actuals/"), body, format="json").json()
    usd = next(row for row in data["rows"] if row["currency"] == "USD")
    assert usd["actual_cost"] == "13062400.00" and usd["cost_deviation"] == "412400.00"
    assert data["deviation_amount"] == "-412400.00"

    client.post(_url(world, "purchase-actuals/"), {"currency": "USD", "rate": "12700"}, format="json")
    assert DealPurchaseActual.objects.filter(deal=world.deal).count() == 1  # одна строка на валюту
    log = ActivityLog.objects.filter(deal_id=world.deal.pk, event_code="deal.purchase_actual_set").latest("id")
    assert log.before_data["rate"] == "12800" and log.after_data["rate"] == "12700"

    data = client.delete(_url(world, "purchase-actuals/USD/")).json()
    assert data["deviation_amount"] == "0.00" and data["has_actuals"] is False
    assert ActivityLog.objects.filter(deal_id=world.deal.pk, event_code="deal.purchase_actual_removed").exists()


def test_rate_defaults_to_table_on_purchase_date(world, sent):
    set_rate("USD", "12720", days_ago=2)
    response = _api(world.finance).post(
        _url(world, "purchase-actuals/"),
        {"currency": "USD", "purchased_on": str(set_rate("USD", "12720", days_ago=2))},
        format="json",
    )
    assert response.status_code == 200
    assert DealPurchaseActual.objects.get(deal=world.deal).rate_to_uzs == D("12720")


@pytest.mark.parametrize(
    "body, status, code",
    [
        ({"currency": "EUR", "rate": "14000"}, 400, "PURCHASE_CURRENCY_NOT_IN_QUOTE"),
        ({"currency": "USD", "rate": "0"}, 400, "FX_RATE_INVALID"),
        ({"currency": "USD", "amount": "-5", "rate": "12000"}, 400, "PURCHASE_AMOUNT_INVALID"),
        ({"currency": "USD", "amount": "1.001", "rate": "12000"}, 400, "PURCHASE_AMOUNT_INVALID"),
        ({"currency": "USD", "rate": "12000", "purchased_on": "2999-01-01"}, 400, "PURCHASE_DATE_IN_FUTURE"),
        ({"currency": "USD", "purchased_on": "2020-01-01"}, 400, "FX_RATE_MISSING"),
    ],
)
def test_record_actual_validation(world, sent, body, status, code):
    response = _api(world.finance).post(_url(world, "purchase-actuals/"), body, format="json")
    assert response.status_code == status
    assert response.json()["detail"] == code


def test_uzs_actual_forces_rate_one(world, sent):
    response = _api(world.finance).post(
        _url(world, "purchase-actuals/"), {"currency": "UZS", "amount": "2100000", "rate": "5"}, format="json"
    )
    assert response.status_code == 200
    uzs = next(row for row in response.json()["rows"] if row["currency"] == "UZS")
    assert uzs["actual_rate"] == "1" and uzs["cost_deviation"] == "100000.00"


def test_record_without_sent_quote_conflicts(world):
    set_rate("USD", "12650")
    build_quote(world, [("100", "USD", 1)])
    response = _api(world.finance).post(_url(world, "purchase-actuals/"), {"currency": "USD"}, format="json")
    assert response.status_code == 409
    assert response.json()["detail"] == "MARGIN_NO_REFERENCE_QUOTE"
