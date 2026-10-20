"""FIX-41 (F-3): лимит возраста курса — из настроек СВОЕЙ компании; переменная окружения — только запасное значение."""

import datetime

import pytest
from django.utils import timezone
from finance.services.fx import max_rate_age_days, resolve_rate
from parties.models import CompanySettings
from sales.tests.helpers_fx import set_rate

from accounts.models import Company, CompanyMember, CustomUser, WorkspaceRole
from accounts.testing import make_own_company

pytestmark = pytest.mark.django_db


def _company(name, inn, *, own=False, max_age=None):
    company = Company.objects.create(name=name, inn=inn)
    user = CustomUser.objects.create_user(
        email=f"{inn}@x.test", username=f"{inn}@x.test", password=None, is_active=True
    )
    CompanyMember.objects.create(
        user=user, company=company, role=WorkspaceRole.objects.get_or_create(code="MEMBER", defaults={"name": "m"})[0]
    )
    if own:
        make_own_company(company)
    if max_age is not None:
        CompanySettings.objects.update_or_create(company=company, defaults={"fx_rate_max_age_days": max_age})
    return company


def test_two_companies_limit_comes_from_own_company_not_first_row(settings):
    """Чужая компания заведена первой (меньший id) и имеет другой лимит — берётся лимит своей компании."""
    settings.OWN_COMPANY_ID = None
    _company("Чужая", "5000000001", max_age=30)
    own = _company("Своя", "5000000002", own=True, max_age=3)

    assert max_rate_age_days() == 3
    assert max_rate_age_days(own) == 3

    set_rate("USD", "12600", days_ago=5)  # 5 дней: по лимиту своей компании (3) курса нет, по чужому (30) — был бы
    assert resolve_rate("USD") is None
    set_rate("USD", "12700", days_ago=2)
    assert resolve_rate("USD").rate_date == timezone.localdate() - datetime.timedelta(days=2)


def test_own_company_setting_beats_environment(settings):
    """Раньше любое значение окружения, кроме 7, перебивало настройку компании."""
    settings.OWN_COMPANY_ID = None
    settings.FX_RATE_MAX_AGE_DAYS = 2
    _company("Своя", "5000000003", own=True, max_age=10)

    assert max_rate_age_days() == 10
    set_rate("USD", "12600", days_ago=6)
    assert resolve_rate("USD") is not None


def test_explicit_own_company_id_setting_wins_over_other_rows(settings):
    other = _company("Чужая", "5000000004", max_age=45)
    own = _company("Своя", "5000000005", own=True, max_age=4)
    settings.OWN_COMPANY_ID = own.pk

    assert max_rate_age_days() == 4
    assert max_rate_age_days(other) == 45  # явно переданная компания — её настройка


def test_environment_is_only_fallback_without_settings_row(settings):
    settings.OWN_COMPANY_ID = None
    settings.FX_RATE_MAX_AGE_DAYS = 9
    _company("Своя без настроек", "5000000006", own=True)  # строки CompanySettings нет

    assert max_rate_age_days() == 9


def test_environment_fallback_when_no_own_company_and_foreign_rows_ignored(settings):
    """Своей компании нет (пустая система): запасное значение окружения, а не «первая попавшаяся» строка."""
    settings.OWN_COMPANY_ID = None
    settings.FX_RATE_MAX_AGE_DAYS = 5
    CompanySettings.objects.create(
        company=Company.objects.create(name="Случайная", inn="5000000007"), fx_rate_max_age_days=60
    )

    assert max_rate_age_days() == 5


def test_misconfigured_two_sellers_falls_back_to_environment(settings):
    """Две «своих» компании без OWN_COMPANY_ID — не падаем в пересчёте КП, берём запасное значение."""
    settings.OWN_COMPANY_ID = None
    settings.FX_RATE_MAX_AGE_DAYS = 6
    _company("Своя 1", "5000000008", own=True, max_age=20)
    _company("Своя 2", "5000000009", own=True, max_age=25)

    assert max_rate_age_days() == 6


# ── FIX-54 (F-15): лимит возраста курса читается один раз на вызов, а не на каждую валюту ─────────────


def _companysettings_reads(ctx):
    return [q for q in ctx.captured_queries if "parties_companysettings" in q["sql"] and q["sql"].startswith("SELECT")]


def test_resolve_rate_costs_one_settings_read_and_no_company_row(settings, django_assert_num_queries):
    own = _company("Своя", "5000000011", own=True, max_age=5)
    settings.OWN_COMPANY_ID = own.pk
    set_rate("USD", "12600", days_ago=1)
    with django_assert_num_queries(2):  # настройка компании + курс; строка самой компании не читается
        assert resolve_rate("USD") is not None


def test_explicit_max_age_skips_the_settings_lookup(settings, django_assert_num_queries):
    own = _company("Своя", "5000000012", own=True, max_age=2)
    settings.OWN_COMPANY_ID = own.pk
    set_rate("USD", "12600", days_ago=5)
    with django_assert_num_queries(1):  # только курс
        assert resolve_rate("USD", max_age_days=10) is not None
    with django_assert_num_queries(1):
        assert resolve_rate("USD", max_age_days=3) is None


def test_fx_market_of_the_quote_builder_reads_the_age_limit_once(settings):
    from decimal import Decimal

    from django.db import connection
    from django.test.utils import CaptureQueriesContext
    from master_data.models import Currency
    from rest_framework.test import APIRequestFactory

    from crm.models import Deal, DealStage, Quote, QuoteStatus
    from crm.serializers import QuoteSerializer

    own = _company("Своя", "5000000013", own=True, max_age=5)
    settings.OWN_COMPANY_ID = own.pk
    for code in ("USD", "EUR", "GBP", "RUB"):
        Currency.objects.update_or_create(code=code, defaults={"name": code, "is_active": True})
        set_rate(code, "12600", days_ago=1)
    stage = DealStage.objects.get_or_create(code="DRAFT", defaults={"name": "Draft", "sort_order": 10})[0]
    status = QuoteStatus.objects.get_or_create(code="DRAFT", defaults={"name": "Draft", "sort_order": 10})[0]
    deal = Deal.objects.create(title="КП", company=own, stage=stage)
    quote = Quote.objects.create(deal=deal, version=1, status=status, vat_rate=Decimal("12"))
    request = APIRequestFactory().get("/")
    request.user = CustomUser.objects.get(email="5000000013@x.test")
    serializer = QuoteSerializer(quote, context={"request": request, "include_economics": True})

    with CaptureQueriesContext(connection) as ctx:
        market = serializer.get_fx_market(quote)

    assert {"USD", "EUR", "GBP", "RUB"} <= set(market)
    assert len(_companysettings_reads(ctx)) == 1, [q["sql"] for q in ctx.captured_queries]


def test_quote_rate_map_reads_the_age_limit_once_for_all_currencies(settings):
    from decimal import Decimal

    from django.db import connection
    from django.test.utils import CaptureQueriesContext
    from sales.services.quote_fx import resolve_quote_rate_map

    from crm.models import Deal, DealStage, Quote, QuoteStatus

    own = _company("Своя", "5000000014", own=True, max_age=5)
    settings.OWN_COMPANY_ID = own.pk
    for code in ("USD", "EUR", "GBP"):
        set_rate(code, "12600", days_ago=1)
    stage = DealStage.objects.get_or_create(code="DRAFT", defaults={"name": "Draft", "sort_order": 10})[0]
    status = QuoteStatus.objects.get_or_create(code="DRAFT", defaults={"name": "Draft", "sort_order": 10})[0]
    quote = Quote.objects.create(
        deal=Deal.objects.create(title="КП", company=own, stage=stage), version=1, status=status, vat_rate=Decimal("12")
    )
    with CaptureQueriesContext(connection) as ctx:
        rate_map = resolve_quote_rate_map(quote, ["USD", "EUR", "GBP"])
    assert {"USD", "EUR", "GBP"} <= set(rate_map) and all(rate_map[c] == Decimal("12600") for c in ("USD", "EUR", "GBP"))
    assert len(_companysettings_reads(ctx)) == 1
