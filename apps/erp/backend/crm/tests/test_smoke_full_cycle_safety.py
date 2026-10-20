"""FIX-43 (F-8): `smoke_full_cycle` — dev-команда, безопасная для настоящих данных.

Раньше она без проверки окружения переписывала курс USD на сегодня, реквизиты настоящей
`own_company()`, делала smoke-менеджера суперпользователем, а `--cleanup` удалял «свою» компанию.
Каждый пункт — отдельный тест; сквозной цикл гоняется по-настоящему (он и есть проверка, что без
суперпользователя и без правки чужого он проходит).
"""

import datetime
from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone

from accounts.models import Company, CompanyMember, CompanyType, CustomUser, WorkspaceRole
from core.models import ExchangeRate
from core.tenant import own_company
from master_data.models import Currency

SMOKE_EMAILS = ["smoke.supplier@example.test", "smoke.manager@example.test"]


@pytest.fixture(autouse=True)
def _debug_on(settings):
    settings.DEBUG = True
    settings.OWN_COMPANY_ID = None


def _run(*args):
    out = StringIO()
    call_command("smoke_full_cycle", *args, stdout=out)
    return out.getvalue()


@pytest.fixture
def real_company(db):
    """Настоящая своя компания: продавец с сотрудником, реквизиты заполнены «боевыми» значениями."""
    company = Company.objects.create(
        name="Настоящая Компания", inn="301234567", bank_account="20208000999999999999", mfo="00999"
    )
    company.types.add(CompanyType.objects.get(code="SUPPLIER"))
    user = CustomUser.objects.create_user(email="real.boss@example.test", username="real_boss", password="pw")
    CompanyMember.objects.create(
        user=user,
        company=company,
        role=WorkspaceRole.objects.get(code="OWNER"),
        is_primary=True,
        is_active=True,
        can_sell=True,
    )
    return company


def _usd():
    return Currency.objects.get_or_create(code="USD", defaults={"name": "US Dollar", "symbol": "$", "sort_order": 10})[
        0
    ]


def _requisites(company):
    company.refresh_from_db()
    return (company.name, company.inn, company.bank_account, company.mfo, company.legal_address, company.email)


# ── 1. Только DEBUG ─────────────────────────────────────────────────────────


def test_refuses_to_run_without_debug_and_writes_nothing(db, settings):
    settings.DEBUG = False
    users_before = CustomUser.objects.count()

    with pytest.raises(CommandError, match="DEBUG=False"):
        _run()

    assert CustomUser.objects.count() == users_before
    assert not Company.objects.filter(inn__startswith="99900000").exists()
    assert not ExchangeRate.objects.filter(source="SMOKE").exists()


# ── 2. Реальный курс не трогается ───────────────────────────────────────────


def test_todays_real_rate_is_left_alone(db):
    usd = _usd()
    real = ExchangeRate.objects.create(
        currency=usd, rate_date=timezone.localdate(), rate_to_uzs=Decimal("12345.678900"), source="CBU"
    )

    _run()

    real.refresh_from_db()
    assert (real.rate_to_uzs, real.source) == (Decimal("12345.678900"), "CBU")
    assert ExchangeRate.objects.filter(currency=usd).count() == 1


def test_a_recent_real_rate_is_used_not_shadowed_by_a_fake_one(db):
    """Курс вчерашний — он всё ещё действующий: фальшивая строка «на сегодня» перекрыла бы его для всех КП."""
    usd = _usd()
    yesterday = timezone.localdate() - datetime.timedelta(days=1)
    ExchangeRate.objects.create(currency=usd, rate_date=yesterday, rate_to_uzs=Decimal("12100.000000"), source="CBU")

    _run()

    assert list(ExchangeRate.objects.filter(currency=usd).values_list("source", flat=True)) == ["CBU"]


def test_without_any_rate_it_adds_its_own_labelled_one_and_cleanup_removes_it(db):
    usd = _usd()
    ExchangeRate.objects.filter(currency=usd).delete()

    _run()
    assert ExchangeRate.objects.get(currency=usd).source == "SMOKE"

    _run("--cleanup")
    assert not ExchangeRate.objects.filter(currency=usd).exists()


def test_cleanup_keeps_real_rates(db):
    usd = _usd()
    real = ExchangeRate.objects.create(
        currency=usd, rate_date=timezone.localdate(), rate_to_uzs=Decimal("12345.000000"), source="CBU"
    )

    _run("--cleanup")

    assert ExchangeRate.objects.filter(pk=real.pk).exists()


# ── 3. Реквизиты настоящей own_company не трогаются ─────────────────────────


def test_real_own_company_requisites_and_identity_survive_the_run(real_company):
    before = _requisites(real_company)

    _run()

    assert _requisites(real_company) == before
    # Вторая компания-продавец с сотрудниками не должна сделать «свою компанию» неоднозначной.
    assert own_company().pk == real_company.pk


def test_real_company_with_empty_requisites_is_not_filled_in(real_company):
    """Раньше пустые `bank_account`/`mfo` настоящей компании «дописывались» значениями smoke."""
    real_company.bank_account = ""
    real_company.mfo = ""
    real_company.save(update_fields=["bank_account", "mfo"])

    _run()

    real_company.refresh_from_db()
    assert (real_company.bank_account, real_company.mfo) == ("", "")


def test_own_company_setting_is_restored_after_the_run(real_company, settings):
    settings.OWN_COMPANY_ID = real_company.pk

    _run()

    assert settings.OWN_COMPANY_ID == real_company.pk
    assert own_company().pk == real_company.pk


# ── 4. Не оставляет суперпользователя ───────────────────────────────────────


def test_no_superuser_is_left_behind(db):
    assert not CustomUser.objects.filter(is_superuser=True).exists()

    _run()

    assert not CustomUser.objects.filter(is_superuser=True).exists()
    manager = CustomUser.objects.get(email="smoke.manager@example.test")
    assert not manager.is_superuser and not manager.is_staff
    assert not manager.has_usable_password()


def test_a_superuser_smoke_manager_from_an_old_run_is_demoted(db):
    CustomUser.objects.create_user(
        email="smoke.manager@example.test",
        username="smoke.manager@example.test",
        is_staff=True,
        is_superuser=True,
    )

    _run()

    assert not CustomUser.objects.get(email="smoke.manager@example.test").is_superuser


def test_smoke_staff_memberships_are_not_left_active(db):
    _run()

    smoke_company = Company.objects.get(inn="999000002")
    assert not CompanyMember.objects.filter(company=smoke_company, is_active=True).exists()


# ── 5. --cleanup: только созданное, никогда — своя компания ─────────────────


def test_cleanup_removes_only_what_the_command_created(real_company):
    real_user = CustomUser.objects.get(email="real.boss@example.test")
    real_requisites = _requisites(real_company)
    real_members = CompanyMember.objects.filter(company=real_company).count()

    _run("--cleanup")

    assert not Company.objects.filter(inn__in=["999000001", "999000002"]).exists()
    assert not CustomUser.objects.filter(email__in=SMOKE_EMAILS).exists()
    assert not CustomUser.objects.filter(email="smoke.client@example.test").exists()
    # Своя компания, её сотрудник и реквизиты — на месте.
    assert CustomUser.objects.filter(pk=real_user.pk).exists()
    assert _requisites(real_company) == real_requisites
    assert CompanyMember.objects.filter(company=real_company).count() == real_members
    assert own_company().pk == real_company.pk


def test_cleanup_never_deletes_the_own_company_even_if_it_is_the_only_seller(db):
    """Единственная настоящая компания-продавец (без smoke-прогона) переживает --cleanup."""
    only = Company.objects.create(
        name="Единственный Продавец", inn="301111111", bank_account="20208000111", mfo="00111"
    )
    only.types.add(CompanyType.objects.get(code="SUPPLIER"))
    user = CustomUser.objects.create_user(email="only.boss@example.test", username="only_boss", password="pw")
    CompanyMember.objects.create(
        user=user, company=only, role=WorkspaceRole.objects.get(code="OWNER"), is_primary=True, is_active=True
    )

    _run("--cleanup")

    assert Company.objects.filter(pk=only.pk).exists()
    assert own_company().pk == only.pk


def test_a_foreign_company_with_the_smoke_inn_is_refused_and_survives(db):
    foreign = Company.objects.create(name="Чужая Компания", inn="999000002", bank_account="20208000777", mfo="00777")

    for args in ((), ("--cleanup",)):
        with pytest.raises(CommandError, match="999000002"):
            _run(*args)

    survived = Company.objects.get(pk=foreign.pk)
    assert (survived.name, survived.bank_account, survived.mfo) == ("Чужая Компания", "20208000777", "00777")
    assert not CustomUser.objects.filter(email__in=SMOKE_EMAILS).exists(), "прогон откатился целиком"


# ── 6. Цикл по-прежнему проходит и повторяем ────────────────────────────────


def test_the_cycle_passes_end_to_end_without_a_superuser_and_is_repeatable_after_cleanup(db):
    """Сквозной цикл идёт обычным сотрудником: подпись клиента — контактом (как в портале), сделка закрывается."""
    from crm.models import Deal

    first = _run()
    assert "SUCCESS" in first
    assert Deal.objects.get(title="Smoke E2E deal").stage.code == "CLOSED_WON"
    assert not CustomUser.objects.filter(is_superuser=True).exists()

    _run("--cleanup")
    assert not Deal.objects.filter(title="Smoke E2E deal").exists()
    assert "SUCCESS" in _run()


def test_a_failed_cycle_leaves_nothing_behind(db, monkeypatch):
    """Прогон идёт в одной транзакции: сорвался шаг — ни компаний, ни аккаунтов, и настройка возвращена."""
    from django.conf import settings

    from crm import services

    def boom(*args, **kwargs):
        return None, "BOOM"

    monkeypatch.setattr(services, "generate_contract_from_quote", boom)

    with pytest.raises(Exception, match="BOOM"):
        _run()

    assert not Company.objects.filter(inn__in=["999000001", "999000002"]).exists()
    assert not CustomUser.objects.filter(email__in=SMOKE_EMAILS).exists()
    assert settings.OWN_COMPANY_ID is None
