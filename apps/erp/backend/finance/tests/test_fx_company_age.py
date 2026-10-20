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
