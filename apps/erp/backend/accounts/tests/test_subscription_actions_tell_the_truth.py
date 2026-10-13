"""
Операторские действия над подпиской перестали врать (находки 46, 47, 51 прогона 20-08).

Замеры 25-08:

* **46.** `POST subscriptions/{id}/activate/` на подписке с `valid_until` в прошлом отдавал
  200 и рисовал ACTIVE, но `is_operational` оставался False: платные пути по-прежнему били
  `SUBSCRIPTION_REQUIRED`, реестр показывал «Активна», `/me` отдавал
  `subscription_active=False` — врали обе витрины сразу, — а ночная задача через сутки
  откатывала статус. Доступ считается по ДВУМ признакам (статус И дата), поэтому смена
  одного статуса не возобновляет подписку. У Stripe и Odoo возобновление — это новый период.
* **47.** `pay/` принимал `months=-2` → 200 и `valid_until` уезжал на 60 дней НАЗАД:
  подписка мгновенно переставала работать, а интерфейс печатал успех. Нечисловое значение
  давало 500 с HTML вместо `{"detail": "<CODE>"}`.
* **51.** Отказ `IsPlatformAdmin` приходил человеческой фразой, а не кодом — витрина не могла
  его перевести и печатала системный `ERR_BAD_REQUEST` от axios. Это касалось ЛЮБОГО отказа
  по правам во всей операторской плоскости, а не только подписок.
"""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import (
    Company,
    CompanyMember,
    CompanyType,
    CustomUser,
    SupplierSubscription,
    SystemRole,
    VerificationStatus,
    WorkspaceRole,
)


def _api(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.fixture
def world(db):
    WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})
    CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 20})

    company = Company.objects.create(
        name="Продавец подписки",
        inn="907800001",
        verification_status=VerificationStatus.objects.get(code="L2_VERIFIED"),
    )
    company.types.add(CompanyType.objects.get(code="SUPPLIER"))
    seller = CustomUser.objects.create_user(
        email="seller@subs.test", username="seller_subs", password="x", is_active=True
    )
    CompanyMember.objects.create(
        user=seller,
        company=company,
        role=WorkspaceRole.objects.get(code="OWNER"),
        is_active=True,
        is_primary=True,
        can_sell=True,
    )

    operator = CustomUser.objects.create_user(
        email="billing@subs.test",
        username="billing_subs",
        password="x",
        role=SystemRole.objects.get(code="ADMIN"),
        is_superuser=True,
        is_active=True,
    )
    viewer = CustomUser.objects.create_user(
        email="viewer@subs.test",
        username="viewer_subs",
        password="x",
        role=SystemRole.objects.get(code="ADMIN"),
        is_active=True,
    )

    expired = SupplierSubscription.objects.create(
        company=company,
        plan="PREMIUM",
        status="PAST_DUE",
        valid_until=timezone.localdate() - timedelta(days=10),
    )
    return {"company": company, "seller": seller, "operator": operator, "viewer": viewer, "sub": expired}


# ── 46. Активация просроченной подписки ─────────────────────────────────────


def test_activating_an_expired_subscription_is_refused_not_faked(world):
    resp = _api(world["operator"]).post(f"/api/v1/accounts/subscriptions/{world['sub'].pk}/activate/")

    assert resp.status_code == 400
    assert resp.json()["detail"] == "SUBSCRIPTION_EXPIRED_EXTEND_FIRST"
    world["sub"].refresh_from_db()
    assert world["sub"].status == "PAST_DUE", "статус не должен рисоваться активным"


def test_the_refusal_is_about_ACCESS_not_just_the_status_field(world):
    """Проверяем СМЫСЛ: витрина и доступ обязаны говорить ОДНО И ТО ЖЕ.

    Осторожно с формулировкой: «доступа нет» само по себе было верно и ДО починки (дата в
    прошлом), поэтому тест на один `assert_seller_can_operate` был бы зелёным на сломанном
    коде. Ловит дефект именно связка: статус НЕ нарисован активным И доступа нет.
    """
    from accounts.services import assert_seller_can_operate

    _api(world["operator"]).post(f"/api/v1/accounts/subscriptions/{world['sub'].pk}/activate/")

    world["sub"].refresh_from_db()
    assert world["sub"].status != "ACTIVE", "витрина не должна показывать активной подписку без доступа"
    assert world["sub"].is_operational is False
    assert assert_seller_can_operate(world["seller"]) == "SUBSCRIPTION_REQUIRED"


def test_payment_really_renews_the_subscription(world):
    """Обратная сторона: путь возобновления существует и работает — это оплата."""
    resp = _api(world["seller"]).post(
        f"/api/v1/accounts/subscriptions/{world['sub'].pk}/pay/",
        {"amount": "500000", "months": 1},
        format="json",
    )

    assert resp.status_code == 200, resp.content
    world["sub"].refresh_from_db()
    assert world["sub"].is_operational is True
    assert world["sub"].valid_until > timezone.localdate()


def _live_subscription(inn: str) -> SupplierSubscription:
    """Подписка — ОДНА на компанию (OneToOne), поэтому живой нужна своя."""
    other = Company.objects.create(name=f"Компания {inn}", inn=inn)
    other.types.add(CompanyType.objects.get(code="SUPPLIER"))
    return SupplierSubscription.objects.create(
        company=other,
        plan="BASIC",
        status="SUSPENDED",
        valid_until=timezone.localdate() + timedelta(days=30),
    )


def test_a_live_subscription_still_activates(world, db):
    """Запрет не превратился в «активировать нельзя ничего»."""
    live = _live_subscription("907800002")

    resp = _api(world["operator"]).post(f"/api/v1/accounts/subscriptions/{live.pk}/activate/")

    assert resp.status_code == 200, resp.content
    live.refresh_from_db()
    assert live.status == "ACTIVE"
    assert live.is_operational is True


def test_bulk_activation_reports_the_ones_it_skipped(world, db):
    live = _live_subscription("907800003")

    resp = _api(world["operator"]).post(
        "/api/v1/accounts/subscriptions/bulk-set-status/",
        {"ids": [world["sub"].pk, live.pk], "status": "ACTIVE"},
        format="json",
    )

    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body["affected"] == 1
    assert body["skipped_expired"] == [world["sub"].pk], "оператор обязан узнать, кого пропустили"
    world["sub"].refresh_from_db()
    assert world["sub"].status == "PAST_DUE"


# ── 47. Оплата с бессмысленным вводом ───────────────────────────────────────


@pytest.mark.parametrize("months", [-2, 0, 61])
def test_payment_refuses_a_period_that_is_not_forward(world, months):
    before = world["sub"].valid_until

    resp = _api(world["seller"]).post(
        f"/api/v1/accounts/subscriptions/{world['sub'].pk}/pay/",
        {"amount": "500000", "months": months},
        format="json",
    )

    assert resp.status_code == 400
    assert resp.json()["detail"] == "INVALID_MONTHS"
    world["sub"].refresh_from_db()
    assert world["sub"].valid_until == before, "отказ обязан ничего не менять"


def test_non_numeric_months_is_a_refusal_not_a_five_hundred(world):
    """`int(...)` на сыром вводе падал в 500 с HTML — нарушение формы `{"detail": "<CODE>"}`."""
    resp = _api(world["seller"]).post(
        f"/api/v1/accounts/subscriptions/{world['sub'].pk}/pay/",
        {"amount": "500000", "months": "abc"},
        format="json",
    )

    assert resp.status_code == 400
    assert resp.json() == {"detail": "INVALID_MONTHS"}


def test_negative_amount_is_refused(world):
    resp = _api(world["seller"]).post(
        f"/api/v1/accounts/subscriptions/{world['sub'].pk}/pay/",
        {"amount": "-500", "months": 1},
        format="json",
    )

    assert resp.status_code == 400
    assert resp.json()["detail"] == "INVALID_AMOUNT"


def test_a_sane_payment_still_goes_through(world):
    resp = _api(world["seller"]).post(
        f"/api/v1/accounts/subscriptions/{world['sub'].pk}/pay/",
        {"amount": Decimal("120000"), "months": 3},
        format="json",
    )

    assert resp.status_code == 200, resp.content
    world["sub"].refresh_from_db()
    assert world["sub"].valid_until >= timezone.localdate() + timedelta(days=85)


# ── 51. Отказ по правам читается словами, а не системным кодом ──────────────


def test_permission_refusal_arrives_as_a_translatable_code(world):
    """Отказ приходил ФРАЗОЙ — витрина не могла её перевести и печатала `ERR_BAD_REQUEST`
    от axios. После M1-ERP-02 отказывает `IsPlatformAdmin`: администратор = суперпользователь,
    носитель SystemRole=ADMIN без него — обычный пользователь."""
    resp = _api(world["viewer"]).post(f"/api/v1/accounts/subscriptions/{world['sub'].pk}/activate/")

    assert resp.status_code == 403
    detail = str(resp.json()["detail"])
    assert detail == "PLATFORM_ADMIN_REQUIRED", detail
    assert detail.isupper() or "_" in detail, "код, а не человеческая фраза"


def test_view_only_operator_changes_nothing(world):
    """Гарантия на месте: гашение кнопок — удобство, отказ сервера — защита."""
    before = world["sub"].status

    _api(world["viewer"]).post(f"/api/v1/accounts/subscriptions/{world['sub'].pk}/suspend/")

    world["sub"].refresh_from_db()
    assert world["sub"].status == before
