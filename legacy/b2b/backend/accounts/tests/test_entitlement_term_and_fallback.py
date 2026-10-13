"""
Право компании: исключение с истёкшим сроком отступает к правилу подписки, а последний день
срока засчитывается (находки 49 и 50 прогона 20-08, замерены скептиками 25-08).

**49.** Судьбу функции решало само СУЩЕСТВОВАНИЕ строки `CompanyEntitlement`. Истёкшее промо
или исчерпанный пакет кредитов навсегда запирали функцию даже у компании с оплаченной
подпиской: она теряла то, за что платит. Явный ЗАПРЕТ — другое дело, он побеждает всегда,
иначе отключение права было бы бессмысленным.

**50.** Срок задаётся ДАТОЙ (`<input type="date">`) и приезжал полуночью: право «Действует до
25.08» было мертво весь день 25.08. Замер скептика показал, что предложенная в находке замена
`<` на `<=` не изменила бы НИЧЕГО — это сравнение времени со временем, сдвиг на микросекунду.
Причина в рассогласовании типов, и рядом лежал готовый образец: `SupplierSubscription`
считает по дню (`valid_until < today`) и последний день засчитывает.
"""

from datetime import timedelta

import pytest
from django.utils import timezone

from accounts.constants import FeatureKey
from accounts.models import Company, CompanyEntitlement, CompanyType, SupplierSubscription, VerificationStatus
from accounts.services import consume_credit, has_entitlement, is_demo


@pytest.fixture
def subscribed_company(db):
    """Продавец с ОПЛАЧЕННОЙ подпиской — базовый набор функций ему положен."""
    CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 20})
    company = Company.objects.create(
        name="Платящий продавец",
        inn="907900001",
        verification_status=VerificationStatus.objects.get(code="L2_VERIFIED"),
    )
    company.types.add(CompanyType.objects.get(code="SUPPLIER"))
    SupplierSubscription.objects.create(
        company=company,
        plan="PREMIUM",
        status="ACTIVE",
        valid_until=timezone.localdate() + timedelta(days=365),
    )
    return company


def _grant(company, feature, **kwargs):
    return CompanyEntitlement.objects.create(company=company, feature_key=str(feature), **kwargs)


# ── 49. Недействительное исключение отступает к правилу подписки ────────────


def test_subscription_baseline_works_without_any_row(subscribed_company):
    """Опорная точка: без строки права подписка даёт базовый набор."""
    assert has_entitlement(subscribed_company.pk, FeatureKey.QUOTE_SEND) is True
    assert has_entitlement(subscribed_company.pk, FeatureKey.QUOTE_EXPORT) is True


def test_expired_promo_falls_back_to_the_subscription(subscribed_company):
    """Промо-право кончилось — продавец возвращается к тому, за что платит, а не остаётся
    запертым навсегда."""
    _grant(
        subscribed_company,
        FeatureKey.QUOTE_EXPORT,
        access="ENABLED",
        expires_at=timezone.now() - timedelta(days=2),
    )

    assert has_entitlement(subscribed_company.pk, FeatureKey.QUOTE_EXPORT) is True


def test_exhausted_credit_pack_falls_back_to_the_subscription(subscribed_company):
    """Исчерпанный промо-пакет кредитов гасил безлимитный базовый набор подписчика."""
    _grant(subscribed_company, FeatureKey.QUOTE_SEND, access="ENABLED", credits=0)

    assert has_entitlement(subscribed_company.pk, FeatureKey.QUOTE_SEND) is True
    assert consume_credit(subscribed_company.pk, FeatureKey.QUOTE_SEND) is True


def test_expired_demo_falls_back_too(subscribed_company):
    _grant(
        subscribed_company,
        FeatureKey.AI_DRAFT,
        access="DEMO",
        expires_at=timezone.now() - timedelta(days=1),
    )

    assert has_entitlement(subscribed_company.pk, FeatureKey.AI_DRAFT) is True
    assert is_demo(subscribed_company.pk, FeatureKey.AI_DRAFT) is False, "истёкший DEMO больше не demo"


def test_an_explicit_ban_always_wins(subscribed_company):
    """Обратная сторона: запрет платформы побеждает подписку — иначе отключение права было бы
    бессмысленным."""
    _grant(subscribed_company, FeatureKey.QUOTE_SEND, access="DISABLED")

    assert has_entitlement(subscribed_company.pk, FeatureKey.QUOTE_SEND) is False
    assert consume_credit(subscribed_company.pk, FeatureKey.QUOTE_SEND) is False


def test_a_live_promo_still_decides(subscribed_company, db):
    """И ещё одна обратная сторона: действующее право работает у компании БЕЗ подписки."""
    company = Company.objects.create(name="Без подписки", inn="907900002")
    _grant(company, FeatureKey.QUOTE_SEND, access="ENABLED", expires_at=timezone.now() + timedelta(days=5))

    assert has_entitlement(company.pk, FeatureKey.QUOTE_SEND) is True


def test_expired_row_does_not_rescue_a_company_without_subscription(db):
    """Отступление к правилу подписки — не подарок: без подписки функция закрыта."""
    company = Company.objects.create(name="Ни того ни другого", inn="907900003")
    _grant(
        company,
        FeatureKey.QUOTE_SEND,
        access="ENABLED",
        expires_at=timezone.now() - timedelta(days=1),
    )

    assert has_entitlement(company.pk, FeatureKey.QUOTE_SEND) is False


# ── 50. Последний день срока засчитывается ──────────────────────────────────


def test_the_last_day_of_the_term_still_works(db):
    """«Действует до 25.08» обязано работать ВЕСЬ день 25.08 — так читает подпись человек, и
    так же считает соседняя подписка."""
    company = Company.objects.create(name="Право до сегодня", inn="907900004")
    today_midnight = timezone.make_aware(timezone.datetime.combine(timezone.localdate(), timezone.datetime.min.time()))
    row = _grant(company, FeatureKey.QUOTE_SEND, access="ENABLED", expires_at=today_midnight)

    assert row.is_expired is False
    assert row.is_currently_granted() is True
    assert has_entitlement(company.pk, FeatureKey.QUOTE_SEND) is True


def test_yesterday_is_over(db):
    company = Company.objects.create(name="Право до вчера", inn="907900005")
    yesterday = timezone.make_aware(
        timezone.datetime.combine(timezone.localdate() - timedelta(days=1), timezone.datetime.min.time())
    )
    row = _grant(company, FeatureKey.QUOTE_SEND, access="ENABLED", expires_at=yesterday)

    assert row.is_expired is True
    assert has_entitlement(company.pk, FeatureKey.QUOTE_SEND) is False


def test_a_row_without_a_term_never_expires(db):
    company = Company.objects.create(name="Бессрочное", inn="907900006")
    row = _grant(company, FeatureKey.QUOTE_SEND, access="ENABLED", expires_at=None)

    assert row.is_expired is False
    assert has_entitlement(company.pk, FeatureKey.QUOTE_SEND) is True


def test_the_term_matches_the_neighbouring_subscription_rule(db):
    """Две половины одного продукта обязаны считать срок ОДИНАКОВО: до починки подписка
    засчитывала последний день, а право — нет."""
    company = Company.objects.create(name="Сверка правил", inn="907900007")
    today = timezone.localdate()
    subscription = SupplierSubscription.objects.create(
        company=company, plan="BASIC", status="ACTIVE", valid_until=today
    )
    row = _grant(
        company,
        FeatureKey.QUOTE_SEND,
        access="ENABLED",
        expires_at=timezone.make_aware(timezone.datetime.combine(today, timezone.datetime.min.time())),
    )

    assert subscription.is_operational is True
    assert row.is_expired is False
