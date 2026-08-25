"""
Приостановка подписки доходит до арендатора (находка 54, замерена скептиком 25-08).

Замер: `POST subscriptions/{id}/suspend/` с причиной → 200, статус SUSPENDED, доступ закрыт,
и при этом **Notification +0, EmailLog +0**. Единственный след — запись в журнале доступа,
который арендатору закрыт (`IsPlatformAdmin`). Платящего продавца отрезали от клина молча:
он узнавал об этом, только упёршись в закрытую функцию, и видел там общий текст «нужна
подписка» — причина отключения была ему недоступна вовсе.

Эталон — Stripe: сообщение об ограничении адресовано тому, кого ограничили, и называет
причину. Механика писем и уведомлений здесь копируется с KYC — отправка отложена до
`on_commit`, чтобы письмо не ушло при откате.

Скептик поправил находку: «баннер называет ЧУЖУЮ причину» не подтвердилось — баннер просто
печатал общий текст. Половина заголовка снята.
"""

from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import (
    Company,
    CompanyMember,
    CompanyType,
    CustomUser,
    OperatorRole,
    SupplierSubscription,
    SystemRole,
    VerificationStatus,
    WorkspaceRole,
)
from notifications.models import EmailLog, Notification


def _api(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.fixture
def world(db):
    WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})
    CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 20})

    company = Company.objects.create(
        name="Отключаемый продавец",
        inn="908000001",
        verification_status=VerificationStatus.objects.get(code="L2_VERIFIED"),
    )
    company.types.add(CompanyType.objects.get(code="SUPPLIER"))
    owner = CustomUser.objects.create_user(
        email="owner@suspend.test", username="owner_suspend", password="x", is_active=True
    )
    CompanyMember.objects.create(
        user=owner,
        company=company,
        role=WorkspaceRole.objects.get(code="OWNER"),
        is_active=True,
        is_primary=True,
        can_sell=True,
    )
    role = OperatorRole.objects.create(
        code="SUSPEND_BILLING", name="Биллинг", permissions=["billing.view", "billing.manage"]
    )
    operator = CustomUser.objects.create_user(
        email="operator@suspend.test",
        username="operator_suspend",
        password="x",
        role=SystemRole.objects.get(code="ADMIN"),
        operator_role=role,
        is_active=True,
    )
    subscription = SupplierSubscription.objects.create(
        company=company,
        plan="PREMIUM",
        status="ACTIVE",
        valid_until=timezone.localdate() + timedelta(days=90),
    )
    return {"company": company, "owner": owner, "operator": operator, "sub": subscription}


def _suspend(world, reason="Подозрение в мошенничестве"):
    return _api(world["operator"]).post(
        f"/api/v1/accounts/subscriptions/{world['sub'].pk}/suspend/", {"reason": reason}, format="json"
    )


def test_the_tenant_gets_an_in_app_notification(world, django_capture_on_commit_callbacks):
    before = Notification.objects.filter(user=world["owner"]).count()

    with django_capture_on_commit_callbacks(execute=True):
        resp = _suspend(world)

    assert resp.status_code == 200, resp.content
    assert Notification.objects.filter(user=world["owner"]).count() == before + 1
    notification = Notification.objects.filter(user=world["owner"]).latest("id")
    assert notification.event_code == "subscription.suspended"
    assert "мошенничестве" in notification.message


def test_the_tenant_gets_an_email(world, django_capture_on_commit_callbacks):
    before = EmailLog.objects.count()

    with django_capture_on_commit_callbacks(execute=True):
        _suspend(world)

    assert EmailLog.objects.count() > before, "письмо обязано уйти отключённой стороне"


def test_the_reason_is_visible_to_the_tenant_itself(world, django_capture_on_commit_callbacks):
    """Причина жила ТОЛЬКО в журнале доступа, закрытом правом оператора."""
    with django_capture_on_commit_callbacks(execute=True):
        _suspend(world, reason="Неоплата за два месяца")

    body = _api(world["owner"]).get("/api/v1/accounts/subscriptions/mine/").json()

    assert body["suspended_reason"] == "Неоплата за два месяца"
    assert body["suspended_at"]


def test_the_reason_is_not_a_form_field(world, django_capture_on_commit_callbacks):
    """Приостановка — действие с оповещением, а не поле: иначе причина проставлялась бы
    молча и адресат ничего не узнал бы (тот же класс, что архив компании и уровень KYC)."""
    with django_capture_on_commit_callbacks(execute=True):
        _suspend(world, reason="настоящая причина")

    resp = _api(world["operator"]).patch(
        f"/api/v1/accounts/subscriptions/{world['sub'].pk}/",
        {"suspended_reason": "подменённая причина"},
        format="json",
    )

    assert resp.status_code == 200
    world["sub"].refresh_from_db()
    assert world["sub"].suspended_reason == "настоящая причина"


def test_suspending_twice_is_refused(world, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        _suspend(world)

    second = _suspend(world, reason="ещё раз")

    assert second.status_code == 400
    assert second.json()["detail"] == "SUBSCRIPTION_ALREADY_SUSPENDED"


def test_bulk_suspension_notifies_every_tenant(world, django_capture_on_commit_callbacks, db):
    """Массовый путь — тот же, что одиночный: молчаливое отключение пачки продавцов это тот
    же дефект, только шире."""
    other_company = Company.objects.create(name="Второй продавец", inn="908000002")
    other_company.types.add(CompanyType.objects.get(code="SUPPLIER"))
    other_owner = CustomUser.objects.create_user(
        email="owner2@suspend.test", username="owner2_suspend", password="x", is_active=True
    )
    CompanyMember.objects.create(
        user=other_owner,
        company=other_company,
        role=WorkspaceRole.objects.get(code="OWNER"),
        is_active=True,
        is_primary=True,
        can_sell=True,
    )
    other_sub = SupplierSubscription.objects.create(
        company=other_company,
        plan="BASIC",
        status="ACTIVE",
        valid_until=timezone.localdate() + timedelta(days=30),
    )

    with django_capture_on_commit_callbacks(execute=True):
        resp = _api(world["operator"]).post(
            "/api/v1/accounts/subscriptions/bulk-set-status/",
            {"ids": [world["sub"].pk, other_sub.pk], "status": "SUSPENDED", "reason": "проверка"},
            format="json",
        )

    assert resp.status_code == 200, resp.content
    assert resp.json()["affected"] == 2
    assert Notification.objects.filter(user=world["owner"], event_code="subscription.suspended").exists()
    assert Notification.objects.filter(user=other_owner, event_code="subscription.suspended").exists()


def test_activation_does_not_notify(world, django_capture_on_commit_callbacks):
    """Обратная сторона: канон «ровно столько писем, сколько нужно» — активация письма не
    порождает, иначе оператор рассылал бы спам каждой правкой."""
    with django_capture_on_commit_callbacks(execute=True):
        _suspend(world)
    before = EmailLog.objects.count()

    with django_capture_on_commit_callbacks(execute=True):
        _api(world["operator"]).post(f"/api/v1/accounts/subscriptions/{world['sub'].pk}/activate/")

    assert EmailLog.objects.count() == before
