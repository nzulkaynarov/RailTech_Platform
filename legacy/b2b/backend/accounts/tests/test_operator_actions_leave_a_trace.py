"""Действия оператора обязаны оставлять след с автором (аудит панелей, волна A).

`log_admin_action` и журнал доступа существуют с апреля и используются в KYC, слиянии
компаний, break-glass и МАССОВОЙ смене статуса подписок. Мимо него шли ровно те действия,
которые меняют чужие права и чужие деньги: деактивация аккаунта, смена системной роли, выдача
операторской роли, права-энтайтлменты и ОДИНОЧНАЯ приостановка подписки — при том, что
массовый вариант той же операции на том же экране аудит писал.

Тесты проверяют не «функция вызвана», а наличие записи с АВТОРОМ: без автора запись бесполезна
ровно в том случае, ради которого журнал и заведён — «кто это сделал».
"""

import pytest
from rest_framework.test import APIClient

from accounts.models import (
    Company,
    CompanyEntitlement,
    CompanyMember,
    CompanyRole,
    CustomUser,
    OperatorRole,
    SupplierSubscription,
    SystemRole,
    WorkspaceRole,
)
from accounts.services.members import change_user_role, create_platform_user, toggle_user_active
from accounts.services.operators import assign_operator_role
from crm.models import ActivityLog


@pytest.fixture
def operator(db):
    return CustomUser.objects.create_user(
        email="auditor@trace.test",
        username="auditor_trace",
        password="pw",
        role=SystemRole.objects.get(code="ADMIN"),
        is_active=True,
    )


@pytest.fixture
def victim(db):
    """Обычный пользователь без членств — над ним и производят действия."""
    return CustomUser.objects.create_user(
        email="target@trace.test", username="target_trace", password="pw", is_active=True
    )


@pytest.fixture
def tenant(db):
    company = Company.objects.create(name="Подопечная", inn="770000090")
    owner_role, _ = WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})
    user = CustomUser.objects.create_user(email="ceo@trace.test", username="ceo_trace", password="pw", is_active=True)
    CompanyMember.objects.create(
        user=user,
        company=company,
        role=owner_role,
        company_role=CompanyRole.objects.filter(company=company, is_system=True).first(),
        is_active=True,
        is_primary=True,
    )
    return {"company": company, "user": user}


def _client(user):
    api = APIClient()
    api.force_authenticate(user=user)
    return api


def _entries(entity_type, entity_id):
    return ActivityLog.objects.filter(entity_type=entity_type, entity_id=entity_id)


@pytest.mark.django_db
def test_deactivation_is_recorded_with_its_author(operator, victim):
    """Деактивация — это «удаление» в терминах эталонов; без следа его не отличить от сбоя."""
    toggle_user_active(victim, operator)

    entry = _entries("user", victim.pk).first()
    assert entry is not None, "деактивация не оставила следа"
    assert entry.user_id == operator.pk, "в журнале нет автора"
    assert entry.before_data == {"is_active": True} and entry.after_data == {"is_active": False}


@pytest.mark.django_db
def test_system_role_change_is_recorded(operator, victim):
    """Выдача ADMIN открывает чужие компании, KYC и деньги — след обязателен."""
    change_user_role(victim, "ADMIN", actor=operator, reason="назначен оператором поддержки")

    entry = _entries("user", victim.pk).first()
    assert entry is not None, "смена системной роли не оставила следа"
    assert entry.user_id == operator.pk
    assert entry.after_data == {"role": "ADMIN"}
    assert "поддержки" in entry.reason


@pytest.mark.django_db
def test_role_change_via_endpoint_carries_the_actor(operator, victim):
    """Через вьюсет автор тоже должен доходить — иначе след пишет «никто»."""
    _client(operator).post(f"/api/v1/accounts/users/{victim.pk}/change-role/", {"role": "ADMIN"}, format="json")

    entry = _entries("user", victim.pk).first()
    assert entry is not None and entry.user_id == operator.pk


@pytest.mark.django_db
def test_operator_role_grant_is_recorded(operator):
    """Операторская роль решает, какие чужие данные человек видит (ADR-0004 G1)."""
    target = CustomUser.objects.create_user(
        email="newop@trace.test",
        username="newop_trace",
        password="pw",
        role=SystemRole.objects.get(code="ADMIN"),
        is_active=True,
    )
    role = OperatorRole.objects.create(code="SUPPORT_TRACE", name="Поддержка", permissions=["users.view"])

    assign_operator_role(operator, target.pk, role.pk)

    entry = _entries("user", target.pk).first()
    assert entry is not None, "выдача операторской роли не оставила следа"
    assert entry.user_id == operator.pk
    assert entry.after_data == {"operator_role": "SUPPORT_TRACE"}


@pytest.mark.django_db
def test_user_creation_is_recorded(operator):
    user, _ = create_platform_user(email="fresh@trace.test", actor=operator)

    entry = _entries("user", user.pk).first()
    assert entry is not None and entry.user_id == operator.pk


@pytest.mark.django_db
def test_entitlement_grant_and_revoke_are_recorded(operator, tenant):
    """Строка энтайтлмента ПЕРЕБИВАЕТ подписку — это рычаг монетизации, а не настройка."""
    api = _client(operator)

    created = api.post(
        "/api/v1/admin/entitlements/",
        {"company": tenant["company"].pk, "feature_key": "quote.send", "access": "ENABLED"},
        format="json",
    )
    assert created.status_code == 201, created.data
    entitlement_id = created.data["id"]
    grant = _entries("entitlement", entitlement_id).first()
    assert grant is not None and grant.user_id == operator.pk, "выдача права не оставила следа"

    api.delete(f"/api/v1/admin/entitlements/{entitlement_id}/")

    assert not CompanyEntitlement.objects.filter(pk=entitlement_id).exists()
    assert _entries("entitlement", entitlement_id).count() == 2, "отзыв права не оставил следа"


@pytest.mark.django_db
def test_single_subscription_suspend_is_recorded(operator, tenant):
    """Массовая смена статуса аудит писала, одиночная — нет, на одном и том же экране."""
    subscription = SupplierSubscription.objects.create(company=tenant["company"], status="ACTIVE")

    _client(operator).post(f"/api/v1/accounts/subscriptions/{subscription.pk}/suspend/", {}, format="json")

    entry = _entries("subscription", subscription.pk).first()
    assert entry is not None, "одиночная приостановка не оставила следа"
    assert entry.user_id == operator.pk
    assert entry.after_data == {"status": "SUSPENDED"}


@pytest.mark.django_db
def test_suspend_does_not_demand_a_reason(operator, tenant):
    """Аудит — не гейт: новых блокировок владелец просил не добавлять (PRODUCT RULE 2)."""
    subscription = SupplierSubscription.objects.create(company=tenant["company"], status="ACTIVE")

    response = _client(operator).post(f"/api/v1/accounts/subscriptions/{subscription.pk}/suspend/", {}, format="json")

    assert response.status_code == 200, response.data


# ── Запись с автором не должна ВЫГЛЯДЕТЬ как запись без автора ──────────────


@pytest.mark.django_db
def test_author_without_a_name_is_shown_by_email(operator, victim):
    """`get_full_name()` пуст у служебных и заведённых оператором аккаунтов.

    Найдено глазами: деактивация записалась, автор в базе стоял — а в журнале доступа ячейка
    «Автор» была пустой, то есть выглядела ровно как системное событие без человека.
    """
    operator.first_name = ""
    operator.last_name = ""
    operator.save(update_fields=["first_name", "last_name"])
    toggle_user_active(victim, operator)

    payload = _client(operator).get("/api/v1/crm/activity-logs/", {"entity_type": "user"}).data
    rows = payload["results"] if isinstance(payload, dict) else payload

    assert rows[0]["user_name"] == operator.email, "автор без имени показывается пустым"


@pytest.mark.django_db
def test_system_events_stay_authorless(operator):
    """Откат на email не должен придумывать человека там, где его нет."""
    from core.audit import log_admin_action

    log_admin_action(entity_type="user", entity_id=operator.pk, action="КП просрочено", actor=None)

    payload = _client(operator).get("/api/v1/crm/activity-logs/", {"entity_type": "user"}).data
    rows = payload["results"] if isinstance(payload, dict) else payload

    assert rows[0]["user_name"] == "", "у системного события появился выдуманный автор"


# ── Записано ≠ видно: след обязан доходить до операторского журнала ─────────


def _access_log(operator):
    payload = _client(operator).get("/api/v1/admin/access-log/", {"limit": 50}).data
    return payload["items"]


@pytest.mark.django_db
def test_admin_actions_reach_the_access_log(operator, victim):
    """Волна A писала след, которого оператор НЕ ВИДЕЛ.

    Лента «Журнал доступа» отбирала только break-glass (`expires_at`) и force-override (маркер
    `[FORCE_ADMIN]` в тексте). Деактивация, смена роли, отзыв платного права и приостановка
    подписки в неё не попадали. Эталон — Salesforce Setup Audit Trail: ОДИН список
    административных изменений, а не отдельная витрина под аварийный доступ.
    """
    toggle_user_active(victim, operator)

    entry = next((row for row in _access_log(operator) if row["event_code"] == "admin.user.deactivated"), None)
    assert entry is not None, "деактивация не дошла до журнала доступа"
    assert entry["user_name"] == operator.email
    assert entry["is_break_glass"] is False and entry["is_force_override"] is False


@pytest.mark.django_db
def test_access_log_still_shows_break_glass_and_force_override(operator):
    """Расширение ленты не должно вытеснить то, ради чего она заводилась."""
    from django.utils import timezone

    from core.audit import log_admin_action

    log_admin_action(
        entity_type="company",
        entity_id=1,
        action="BREAK_GLASS открыт доступ",
        actor=operator,
        expires_at=timezone.now() + timezone.timedelta(hours=1),
    )
    log_admin_action(entity_type="contract", entity_id=1, action="[FORCE_ADMIN] Договор отменён", actor=operator)

    rows = _access_log(operator)

    assert any(row["is_break_glass"] for row in rows), "аварийный доступ пропал из ленты"
    assert any(row["is_force_override"] for row in rows), "действие за арендатора пропало из ленты"


@pytest.mark.django_db
def test_access_log_carries_the_machine_code_for_localization(operator, tenant):
    """Без кода лента печатала русскую строку `action` англоязычному оператору."""
    subscription = SupplierSubscription.objects.create(company=tenant["company"], status="ACTIVE")

    _client(operator).post(f"/api/v1/accounts/subscriptions/{subscription.pk}/suspend/", {}, format="json")

    entry = next(row for row in _access_log(operator) if row["event_code"] == "admin.subscription.suspended")
    assert entry["event_params"]["company_name"] == tenant["company"].name


@pytest.mark.django_db
def test_ordinary_deal_events_do_not_flood_the_access_log(operator, tenant):
    """Отбор по `admin.*` не должен затянуть в ленту доступа обычную работу по сделкам."""
    from core.audit import log_admin_action

    log_admin_action(
        entity_type="deal",
        entity_id=1,
        action="Стадия изменена",
        actor=operator,
        event_code="deal.stage_changed",
    )

    assert all(row["event_code"] != "deal.stage_changed" for row in _access_log(operator))
