"""Юнит-тесты сервиса KPI дашборда (`crm.services.dashboard_analytics`).

Логика вынесена из `DashboardAnalyticsView` (Rule 8), и это первый случай, когда её можно
проверять без HTTP. Покрывается то, что через эндпоинт проверялось только на трёх сценариях,
хотя цена ошибки высока: **область видимости — граница конфиденциальности**. Дырка в ней
показывает покупательскому аккаунту цифры другого клиента.

Продавец один — своя компания (M1-ERP-02 волна 3): сотрудник видит все сделки, покупательский
аккаунт — свою компанию. Сценарии через API — в `test_dashboard_scope.py`, здесь то, что дешевле
и точнее проверить на уровне функций.
"""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from accounts.models import Company, CompanyMember, CompanyType, CustomUser, WorkspaceRole
from crm.models import Deal, DealStage, Quote, QuoteStatus
from crm.services.dashboard_analytics import (
    DEFAULT_PERIOD,
    PERIOD_DAYS,
    DashboardScope,
    percentage_change,
    resolve_period_start,
    resolve_scope,
    scope_deals,
)


@pytest.fixture
def lookups(db):
    WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})
    CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Client", "sort_order": 10})
    CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 20})
    DealStage.objects.get_or_create(code="DRAFT", defaults={"name": "Draft", "sort_order": 10})
    QuoteStatus.objects.get_or_create(code="DRAFT", defaults={"name": "Draft", "sort_order": 10})


def _company(name, inn):
    company = Company.objects.create(name=name, inn=inn)
    company.types.add(CompanyType.objects.get(code="CLIENT"))
    return company


def _deal(company, title):
    return Deal.objects.create(title=title, company=company, stage=DealStage.objects.get(code="DRAFT"))


class TestPercentageChange:
    """Стрелка тренда на дашборде. Деление на ноль здесь — это 500 на главной странице."""

    def test_zero_base_gives_zero_not_division_error(self):
        assert percentage_change(0, 100) == 0.0

    def test_growth(self):
        assert percentage_change(100, 150) == 50.0

    def test_decline_is_negative(self):
        assert percentage_change(200, 150) == -25.0

    def test_negative_base_uses_absolute_value(self):
        # Знак базы не должен переворачивать смысл стрелки.
        assert percentage_change(-100, -50) == 50.0

    def test_rounded_to_one_decimal(self):
        assert percentage_change(3, 4) == 33.3


class TestResolvePeriodStart:
    def test_known_periods(self):
        now = timezone.now()
        for period, days in PERIOD_DAYS.items():
            delta = now - resolve_period_start(period)
            assert abs(delta.total_seconds() - timedelta(days=days).total_seconds()) < 5

    def test_unknown_period_falls_back_to_default(self):
        # Произвольная строка в query-параметре не должна ронять дашборд.
        assert abs((resolve_period_start("нечто") - resolve_period_start(DEFAULT_PERIOD)).total_seconds()) < 5


def _member(company, email, **flags):
    user = CustomUser.objects.create_user(email=email, username=email, password="x")
    CompanyMember.objects.create(
        user=user,
        company=company,
        role=WorkspaceRole.objects.get(code="OWNER"),
        is_active=True,
        is_primary=True,
        **flags,
    )
    return user


@pytest.mark.django_db
class TestScopeDeals:
    """Граница конфиденциальности. Каждая ветка проверяется отдельно: ошибка здесь
    показывает одному клиенту сделки другого."""

    def _world(self):
        own = _company("Своя", "S100")
        other = _company("Чужая", "O100")
        mine = _deal(own, "Моя сделка")
        theirs = _deal(other, "Чужая сделка")
        return own, other, mine, theirs

    def test_company_ids_scope_buyer(self, lookups):
        own, _other, mine, _theirs = self._world()
        scope = DashboardScope(False, None, [own.id])
        assert list(scope_deals(Deal.objects.all(), scope)) == [mine]

    def test_staff_sees_everything(self, lookups):
        _own, _other, mine, theirs = self._world()
        scope = DashboardScope(True, None, None)
        assert set(scope_deals(Deal.objects.all(), scope)) == {mine, theirs}

    def test_empty_company_ids_is_not_see_all(self, lookups):
        """Пустой список — это «нет доступа ни к чему», а НЕ «фильтр не задан». Спутать пустой
        список с None здесь означало бы показать постороннему все сделки."""
        self._world()
        scope = DashboardScope(False, None, [])
        assert list(scope_deals(Deal.objects.all(), scope)) == []


@pytest.mark.django_db
class TestResolveScope:
    """Кто есть кто: сотрудник своей компании видит все сделки (KPI каталога — его компания),
    покупательский аккаунт ограничен своими компаниями."""

    def _own_company(self):
        own = Company.objects.create(name="Своя продающая", inn="S900")
        own.types.add(CompanyType.objects.get(code="SUPPLIER"))
        return own

    def test_staff_sees_every_deal(self, lookups):
        own = self._own_company()
        staff = _member(own, "staff@t.test", can_sell=True)
        mine = _deal(_company("Клиент 1", "C901"), "Заявка 1")
        theirs = _deal(_company("Клиент 2", "C902"), "Заявка 2")

        scope = resolve_scope(staff, None)
        assert scope.is_staff is False
        assert scope.seller_company_ids == [own.id]
        assert scope.user_company_ids is None
        assert set(scope_deals(Deal.objects.all(), scope)) == {mine, theirs}

    def test_buyer_is_limited_to_own_companies(self, lookups):
        self._own_company()
        buyer_co = _company("Клиент", "C903")
        buyer = _member(buyer_co, "buyer@t.test")
        mine = _deal(buyer_co, "Моя заявка")
        _deal(_company("Другой клиент", "C904"), "Чужая заявка")

        scope = resolve_scope(buyer, None)
        assert scope.seller_company_ids == []
        assert scope.user_company_ids == [buyer_co.id]
        assert list(scope_deals(Deal.objects.all(), scope)) == [mine]

    def test_superuser_is_staff_scope(self, lookups):
        admin = CustomUser.objects.create_user(email="adm@t.test", username="adm@t.test", password="x")
        admin.is_superuser = True
        admin.save(update_fields=["is_superuser"])
        scope = resolve_scope(admin, None)
        assert scope.is_staff is True
        assert scope.seller_company_ids is None and scope.user_company_ids is None


@pytest.mark.django_db
class TestDashboardAnalyticsCaching:
    """Кэш живёт в сервисе — ключ обязан различать пользователя (и период)."""

    def _user_with_request(self, email):
        from unittest.mock import MagicMock

        company = _company(f"Компания {email}", email[:8])
        user = CustomUser.objects.create_user(email=email, username=email, password="x")
        CompanyMember.objects.create(
            user=user,
            company=company,
            role=WorkspaceRole.objects.get(code="OWNER"),
            is_active=True,
            is_primary=True,
        )
        return user, MagicMock()

    def test_second_call_is_served_from_cache(self, lookups):
        from django.core.cache import cache

        from crm.services.dashboard_analytics import dashboard_analytics

        cache.clear()
        user, request = self._user_with_request("cache@t.test")
        first = dashboard_analytics(user, request, "30d")

        # Новая сделка ПОСЛЕ первого вызова не должна просочиться сквозь минутный TTL —
        # так проверяется, что второй ответ действительно из кэша, а не пересчитан.
        _deal(user.memberships.first().company, "Появилась после кэширования")
        second = dashboard_analytics(user, request, "30d")
        assert second == first

    def test_different_users_do_not_share_cache(self, lookups):
        from django.core.cache import cache

        from crm.services.dashboard_analytics import dashboard_analytics

        cache.clear()
        user_a, request_a = self._user_with_request("a@t.test")
        user_b, request_b = self._user_with_request("b@t.test")
        _deal(user_a.memberships.first().company, "Сделка A")

        data_a = dashboard_analytics(user_a, request_a, "30d")
        data_b = dashboard_analytics(user_b, request_b, "30d")
        assert data_a["active_requests"] == 1
        assert data_b["active_requests"] == 0, "кэш пользователя A утёк пользователю B"


@pytest.mark.django_db
def test_dashboard_payload_keys_are_stable(lookups):
    """Форма ответа — контракт с SPA. Тест ловит выпавший ключ при правке сервиса."""
    from unittest.mock import MagicMock

    from django.core.cache import cache

    from crm.services.dashboard_analytics import dashboard_analytics

    cache.clear()
    company = _company("Покупатель", "B100")
    user = CustomUser.objects.create_user(email="shape@t.test", username="shape@t.test", password="x")
    CompanyMember.objects.create(
        user=user,
        company=company,
        role=WorkspaceRole.objects.get(code="OWNER"),
        is_active=True,
        is_primary=True,
    )
    deal = _deal(company, "Заявка")
    Quote.objects.create(
        deal=deal,
        version=1,
        status=QuoteStatus.objects.get(code="DRAFT"),
        vat_rate=Decimal("12"),
        subtotal_excl_vat=Decimal("1000"),
        vat_amount=Decimal("0"),
        total_incl_vat=Decimal("1000"),
    )
    data = dashboard_analytics(user, MagicMock(), "90d")
    expected = {
        "deals_volume",
        "deals_volume_change",
        "active_requests",
        "active_requests_change",
        "catalog_items",
        "catalog_items_change",
        "clients_count",
        "clients_count_change",
        "deals_by_month",
        "activity_by_day",
        "top_products",
        "counterparties",
        "request_completion",
        "request_completion_goal",
        "deals_in_progress",
        "quotes_received",
        "deals_completed",
    }
    assert expected <= set(data), f"из ответа пропали ключи: {expected - set(data)}"
    assert data["counterparties"].keys() == {"manufacturers", "buyers", "intermediaries"}
