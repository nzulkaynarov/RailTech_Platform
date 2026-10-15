"""M1-ERP-08: правило курса на дату — ближайшая прошедшая дата, не старше FX_RATE_MAX_AGE_DAYS."""

import datetime
from decimal import Decimal

import pytest
from django.utils import timezone
from finance.services.fx import RateSource, convert_to_base, rate_to_str, resolve_rate
from sales.tests.helpers_fx import set_rate

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    "rows, on_days_ago, expected_rate, expected_days_ago",
    [
        ({0: "12650"}, 0, "12650", 0),  # курс на сам день
        ({3: "12600", 10: "12500"}, 0, "12600", 3),  # выходные/праздники — ближайший прошедший
        ({7: "12600"}, 0, "12600", 7),  # граница: ровно 7 дней — ещё курс
        ({8: "12600"}, 0, None, None),  # старше 7 дней — курса нет
        ({-1: "12700"}, 0, None, None),  # только будущий курс — на дату КП курса нет
        ({0: "12700", 5: "12600"}, 5, "12600", 5),  # курс на прошлую дату, а не сегодняшний
        ({2: "0"}, 0, None, None),  # нулевой курс — не курс
    ],
    ids=["same-day", "nearest-previous", "max-age", "too-old", "future-only", "past-date", "zero"],
)
def test_resolve_rate_on_date(rows, on_days_ago, expected_rate, expected_days_ago):
    for days_ago, value in rows.items():
        set_rate("USD", value, days_ago=days_ago)
    on_date = timezone.localdate() - datetime.timedelta(days=on_days_ago)

    resolved = resolve_rate("usd", on_date)

    if expected_rate is None:
        assert resolved is None
    else:
        assert resolved.rate == Decimal(expected_rate)
        assert resolved.rate_date == timezone.localdate() - datetime.timedelta(days=expected_days_ago)
        assert resolved.source == RateSource.CBU


def test_max_age_is_a_setting(settings):
    settings.FX_RATE_MAX_AGE_DAYS = 2
    set_rate("USD", "12600", days_ago=3)
    assert resolve_rate("USD") is None


def test_base_currency_is_one():
    resolved = resolve_rate("UZS")
    assert (resolved.rate, resolved.source) == (Decimal("1"), RateSource.BASE)
    assert resolve_rate("").rate == Decimal("1")


@pytest.mark.parametrize(
    "amount, rate, expected",
    [("100", "12650.5", "1265050.00"), ("0.01", "50.5", "0.51"), ("333.33", "12650.55", "4216807.83")],
)
def test_convert_to_base_rounds_half_up(amount, rate, expected):
    assert convert_to_base(Decimal(amount), Decimal(rate)) == Decimal(expected)


@pytest.mark.parametrize(
    "value, text", [("12650.000000", "12650"), ("12650.550000", "12650.55"), ("0.000001", "0.000001")]
)
def test_rate_to_str_has_no_trailing_zeros(value, text):
    assert rate_to_str(Decimal(value)) == text
