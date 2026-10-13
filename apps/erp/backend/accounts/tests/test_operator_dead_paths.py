"""Пять операторских путей, которые не работали ВООБЩЕ (аудит панелей, 20-08).

Каждый экран существовал, кнопка нажималась, запрос уходил — и упирался в 400/403/415/500 или
в кэш. Тесты держат именно эти пути; отдельная проверка ломаным входом описана в отчёте волны.
"""

import pytest
from django.contrib.auth.models import Group
from django.core.cache import cache
from rest_framework.test import APIClient

from accounts.models import (
    Company,
    CompanyMember,
    CompanyRole,
    CompanyRoleApplication,
    CompanyType,
    CustomUser,
    SystemRole,
    WorkspaceRole,
)
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
        company_role=admin_company_role,
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


# ── 3. Заявки на роль: отказ приходил как 415 ───────────────────────────────


@pytest.mark.django_db
def test_reject_accepts_json(operator, tenant):
    """Классовые `parser_classes` были только multipart — JSON модерации давал 415."""
    supplier, _ = CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Поставщик", "sort_order": 20})
    application = CompanyRoleApplication.objects.create(
        company=tenant["company"], requested_type=supplier, status="PENDING", submitted_by=tenant["user"]
    )

    response = _client(operator).post(
        f"/api/v1/accounts/role-applications/{application.pk}/reject/",
        {"reason": "Нет договора"},
        format="json",
    )

    assert response.status_code != 415, "отказ снова упирается в тип содержимого"
    assert response.status_code == 200, response.data
    application.refresh_from_db()
    assert application.status == "REJECTED"


# ── 4. Заявки на роль: подача была мертва с обеих сторон ────────────────────


@pytest.mark.django_db
def test_company_admin_can_submit_for_own_company(tenant):
    """`company` стал read-only при закрытии M2, а perform_create продолжал его читать → 403."""
    supplier, _ = CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Поставщик", "sort_order": 20})

    response = _client(tenant["user"]).post(
        "/api/v1/accounts/role-applications/", {"requested_type": supplier.pk}, format="json"
    )

    assert response.status_code == 201, response.data
    assert CompanyRoleApplication.objects.get(pk=response.data["id"]).company_id == tenant["company"].pk


@pytest.mark.django_db
def test_operator_must_name_the_company(operator):
    """У оператора членств нет по определению — без явной компании был 500 на NOT NULL."""
    supplier, _ = CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Поставщик", "sort_order": 20})

    response = _client(operator).post(
        "/api/v1/accounts/role-applications/", {"requested_type": supplier.pk}, format="json"
    )

    assert response.status_code == 400, response.data
    assert response.data["detail"] == "COMPANY_REQUIRED"


@pytest.mark.django_db
def test_operator_submits_on_behalf_of_a_tenant(operator, tenant):
    supplier, _ = CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Поставщик", "sort_order": 20})

    response = _client(operator).post(
        "/api/v1/accounts/role-applications/",
        {"requested_type": supplier.pk, "company": tenant["company"].pk},
        format="json",
    )

    assert response.status_code == 201, response.data
    assert CompanyRoleApplication.objects.get(pk=response.data["id"]).company_id == tenant["company"].pk


@pytest.mark.django_db
def test_cannot_file_for_a_foreign_company(tenant):
    """Защита M2 остаётся: своей заявкой нельзя пометить чужого арендатора."""
    supplier, _ = CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Поставщик", "sort_order": 20})
    stranger = Company.objects.create(name="Чужая", inn="770000078")

    response = _client(tenant["user"]).post(
        "/api/v1/accounts/role-applications/",
        {"requested_type": supplier.pk, "company": stranger.pk},
        format="json",
    )

    assert response.status_code == 403
    assert not CompanyRoleApplication.objects.filter(company=stranger).exists()


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


# ── 6. Компания без статуса KYC выпадала из всех вкладок реестра ────────────


@pytest.mark.django_db
def test_new_company_always_has_a_kyc_status():
    """Поле nullable, и часть путей его не заполняла — компания жила «вне вкладок»."""
    company = Company.objects.create(name="Новая", inn="770000079")

    assert company.verification_status_id is not None
    assert company.verification_status.code == "L1_UNVERIFIED"


@pytest.mark.django_db
def test_company_created_by_operator_gets_a_status(operator):
    """`verification_status` read-only в сериализаторе — статус должен ставить сервер."""
    response = _client(operator).post(
        "/api/v1/accounts/companies/", {"name": "Из панели", "inn": "770000080"}, format="json"
    )

    assert response.status_code == 201, response.data
    assert Company.objects.get(inn="770000080").verification_status.code == "L1_UNVERIFIED"


@pytest.mark.django_db
def test_kyc_registry_buckets_add_up(operator, tenant):
    """Сумма вкладок обязана сходиться с итогом — иначе счётчики врут оператору."""
    Company.objects.create(name="Ещё одна", inn="770000081")
    rows = _client(operator).get("/api/v1/accounts/companies/", {"page_size": 200}).data
    rows = rows["results"] if isinstance(rows, dict) else rows

    known = {"L1_UNVERIFIED", "PROFILE_SUBMITTED", "L2_VERIFIED", "L3_CONTRACTED"}
    # Ровно то поле, по которому реестр раскладывает записи по вкладкам (`getStatusCode`).
    codes = [row.get("verification_status_code") for row in rows]

    assert all(code in known for code in codes), f"есть компании вне вкладок: {set(codes) - known}"


@pytest.mark.django_db
def test_existing_status_is_not_overwritten():
    """Подстановка — только на создании: смену статуса делает сервис KYC с аудитом."""
    from accounts.models import VerificationStatus

    verified = VerificationStatus.objects.get(code="L2_VERIFIED")
    company = Company.objects.create(name="Проверенная", inn="770000082", verification_status=verified)

    company.name = "Проверенная (переименована)"
    company.save()
    company.refresh_from_db()

    assert company.verification_status.code == "L2_VERIFIED"
