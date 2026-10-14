"""Пять операторских путей, которые не работали ВООБЩЕ (аудит панелей, 20-08).

Каждый экран существовал, кнопка нажималась, запрос уходил — и упирался в 400/403/415/500 или
в кэш. Тесты держат именно эти пути; отдельная проверка ломаным входом описана в отчёте волны.
"""

import pytest
from django.contrib.auth.models import Group
from django.core.cache import cache
from rest_framework.test import APIClient

from accounts.models import Company, CompanyMember, CompanyRole, CustomUser, SystemRole, WorkspaceRole
from accounts.services.members import can_delete_user, create_platform_user
from master_data.models import UnitOfMeasure


@pytest.fixture
def operator(db):
    admin_role = SystemRole.objects.get(code="ADMIN")
    return CustomUser.objects.create_user(
        is_superuser=True, email="op@dead.test", username="op_dead", password="pw", role=admin_role, is_active=True
    )


@pytest.fixture
def tenant(db):
    """Компания с администратором — тем, кто вправе подавать заявки на роль."""
    company = Company.objects.create(name="Арендатор", inn="770000077")
    owner_role, _ = WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})
    admin_company_role = CompanyRole.objects.filter(company=company, is_system=True).first()
    user = CustomUser.objects.create_user(email="boss@dead.test", username="boss_dead", password="pw", is_active=True)
    CompanyMember.objects.create(
        user=user,
        company=company,
        role=owner_role,
        company_roles=[admin_company_role],
        is_active=True,
        is_primary=True,
    )
    return {"company": company, "user": user}


def _client(user):
    api = APIClient()
    api.force_authenticate(user=user)
    return api


# ── 1. Создание пользователя ────────────────────────────────────────────────


@pytest.mark.django_db
def test_operator_creates_user_without_username(operator):
    """Форма не спрашивает `username` — и не должна: вход по email. Раньше это был 400."""
    response = _client(operator).post(
        "/api/v1/accounts/users/",
        {"email": "New.Person@dead.test", "first_name": "Нина", "role": "USER"},
        format="json",
    )

    assert response.status_code == 201, response.data
    created = CustomUser.objects.get(email="new.person@dead.test")
    assert created.username, "username должен заполняться сервером"
    assert created.is_active is False, "аккаунт активируется, когда человек задал пароль"
    assert created.has_usable_password() is False


@pytest.mark.django_db
def test_created_user_gets_the_password_invite(operator):
    """Без письма аккаунт мёртв: пароль непригоден, а восстановить его человеку нечем."""
    from notifications.models import EmailLog

    _client(operator).post("/api/v1/accounts/users/", {"email": "invited@dead.test"}, format="json")

    log = EmailLog.objects.filter(to_emails__icontains="invited@dead.test").order_by("-id").first()
    assert log is not None, "письмо со ссылкой на установку пароля не ушло"
    assert log.template == "account_created_by_operator"
    assert "setup-password" in (log.body_text or "")


@pytest.mark.django_db
def test_chosen_role_is_applied_not_ignored(operator):
    """Выпадашка роли была декоративной: `role` лежит в read_only_fields UserSerializer."""
    response = _client(operator).post(
        "/api/v1/accounts/users/", {"email": "boss2@dead.test", "role": "ADMIN"}, format="json"
    )

    assert response.status_code == 201, response.data
    assert CustomUser.objects.get(email="boss2@dead.test").role.code == "ADMIN"


@pytest.mark.django_db
def test_duplicate_email_is_named_not_swallowed(operator):
    create_platform_user(email="dup@dead.test")

    response = _client(operator).post("/api/v1/accounts/users/", {"email": "dup@dead.test"}, format="json")

    assert response.status_code == 400
    assert response.data["detail"] == "USER_EMAIL_ALREADY_EXISTS"


# ── 2. Удаление пользователя ────────────────────────────────────────────────


@pytest.mark.django_db
def test_deleting_the_last_company_admin_is_refused(operator, tenant):
    """`CompanyMember.user` каскадный: удаление оставляло компанию без ответственного."""
    response = _client(operator).delete(f"/api/v1/accounts/users/{tenant['user'].pk}/")

    assert response.status_code == 409
    assert response.data["detail"] in {
        "CANNOT_REMOVE_LAST_COMPANY_ADMIN",
        "USER_HAS_HISTORY_DEACTIVATE_INSTEAD",
    }
    assert CustomUser.objects.filter(pk=tenant["user"].pk).exists()


@pytest.mark.django_db
def test_user_with_deal_history_is_not_deleted(operator, tenant):
    """История в pghistory ссылается на пользователя живым FK — удаление падало 500."""
    from crm.models import Deal

    Deal.objects.create(title="Сделка", client=tenant["user"], company=tenant["company"])

    assert can_delete_user(tenant["user"]) is not None


@pytest.mark.django_db
def test_clean_account_still_deletes(operator):
    """Запрет не должен превращаться в «удалить нельзя никогда»."""
    user, _ = create_platform_user(email="clean@dead.test")

    response = _client(operator).delete(f"/api/v1/accounts/users/{user.pk}/")

    assert response.status_code == 204
    assert not CustomUser.objects.filter(pk=user.pk).exists()


# ── 5. Справочники: правка пропадала до десяти минут ────────────────────────


@pytest.mark.django_db
def test_lookup_edit_is_visible_immediately(operator):
    """`cache_page(600)` на том же вьюсете, что и запись, съедал свежую правку."""
    cache.clear()
    unit = UnitOfMeasure.objects.create(code="TSTU", name="старое имя", sort_order=999, is_active=True)
    api = _client(operator)
    assert any(row["id"] == unit.pk for row in api.get("/api/v1/master-data/units/").data)

    api.patch(f"/api/v1/master-data/units/{unit.pk}/", {"name": "новое имя"}, format="json")

    listed = next(row for row in api.get("/api/v1/master-data/units/").data if row["id"] == unit.pk)
    assert listed["name"] == "новое имя", "список отдал устаревшую страницу"


@pytest.mark.django_db
def test_lookup_list_is_still_cached(operator):
    """Кэш не выброшен, а инвалидируется: список справочника читают почти все экраны."""
    cache.clear()
    unit = UnitOfMeasure.objects.create(code="TSTC", name="кэш", sort_order=998, is_active=True)
    api = _client(operator)
    api.get("/api/v1/master-data/units/")

    UnitOfMeasure.objects.filter(pk=unit.pk).update(name="мимо API")

    listed = next(row for row in api.get("/api/v1/master-data/units/").data if row["id"] == unit.pk)
    assert listed["name"] == "кэш", "кэша нет вовсе — каждый экран пойдёт в базу"


# ── Дверь в инженерную админку остаётся закрытой и после этой волны ─────────


@pytest.mark.django_db
def test_created_user_is_not_platform_staff(operator):
    """Создание из панели не должно раздавать доступ в Unfold (волна 20-08)."""
    user, _ = create_platform_user(email="nostaff@dead.test", role_code="ADMIN")

    assert user.is_staff is False
    assert not user.groups.filter(name="system_engineers").exists()
    assert Group.objects.filter(name="system_engineers").exists(), "группа заводится миграцией 0006"


# ── 6. Контрагента заводит бэк-офис (KYC и саморегистрации нет — M1-ERP-02 волна 1c) ──


@pytest.mark.django_db
def test_company_created_by_operator(operator):
    """Компания из панели создаётся сразу рабочей: ни статуса верификации, ни очереди KYC."""
    response = _client(operator).post(
        "/api/v1/accounts/companies/", {"name": "Из панели", "inn": "770000080"}, format="json"
    )

    assert response.status_code == 201, response.data
    assert Company.objects.filter(inn="770000080", is_active=True).exists()
    assert not any(key.startswith("verification") for key in response.data)
