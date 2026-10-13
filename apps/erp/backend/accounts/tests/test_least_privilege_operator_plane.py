"""Наименьшие привилегии ВНУТРИ операторской плоскости (ADR-0004 G1).

Прогон 20-08 нашёл один класс в трёх местах: **право нарисовано в меню, но за скрытой дверью
ничего не стоит**. Оператор «Поддержка», заведённый как ТОЛЬКО ПРОСМОТР, переходил по адресу и
писал платформенные справочники и шаблоны писем; член инженерной группы без единого модельного
права создавал арендатора с выставленным KYC; инженер с правом на модель пользователя сохранял
себе `is_superuser`.

Радиус у всех трёх — вся платформа: валюты и единицы печатаются в документах ВСЕХ арендаторов,
активная строка `EmailTemplate` подменяет файловый шаблон ДЛЯ ВСЕХ получателей.
"""

import pytest
from django.contrib.auth.models import Group, Permission
from rest_framework.test import APIClient

from accounts.models import CustomUser, OperatorRole, SystemRole
from core.admin_site import SYSTEM_ENGINEERS_GROUP

PASSWORD = "Passw0rd!LP"


@pytest.fixture
def view_only_operator(db):
    """Оператор платформы, заведённый как «только просмотр» — без `platform.settings`."""
    role = OperatorRole.objects.create(
        code="LP_SUPPORT",
        name="Поддержка (только просмотр)",
        permissions=["users.view", "companies.view", "kyc.view", "billing.view"],
    )
    return CustomUser.objects.create_user(
        email="lp.support@test.uz",
        username="lp_support",
        password=PASSWORD,
        role=SystemRole.objects.get(code="ADMIN"),
        operator_role=role,
        is_active=True,
    )


def _api(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


# ── Справочники: читать можно всем, писать — по праву ───────────────────────


@pytest.mark.django_db
def test_view_only_operator_cannot_write_lookups(view_only_operator):
    api = _api(view_only_operator)

    created = api.post("/api/v1/master-data/currencies/", {"code": "LPX", "name": "Проба"}, format="json")

    assert created.status_code == 403, f"справочник валют открыт на запись: {created.status_code}"


@pytest.mark.django_db
def test_view_only_operator_cannot_delete_lookups(view_only_operator):
    from master_data.models import UnitOfMeasure

    unit = UnitOfMeasure.objects.create(code="LPU", name="проба", sort_order=999, is_active=True)

    response = _api(view_only_operator).delete(f"/api/v1/master-data/units/{unit.pk}/")

    assert response.status_code == 403
    assert UnitOfMeasure.objects.filter(pk=unit.pk).exists()


@pytest.mark.django_db
def test_lookups_stay_publicly_readable(view_only_operator):
    """Запрет не должен задеть чтение: списки справочников читают почти все экраны."""
    response = _api(view_only_operator).get("/api/v1/master-data/currencies/")

    assert response.status_code == 200


# ── Шаблоны писем: активная строка уходит ВСЕМ получателям ──────────────────


@pytest.mark.django_db
def test_view_only_operator_cannot_edit_email_templates(view_only_operator):
    from notifications.models import EmailTemplate

    template = EmailTemplate.objects.create(key="lp_probe", subject="До правки", html_body="<p>x</p>")

    response = _api(view_only_operator).patch(
        f"/api/v1/admin/email-templates/{template.pk}/", {"subject": "ПОДМЕНА"}, format="json"
    )

    assert response.status_code == 403, "шаблон письма правится оператором «только просмотр»"
    template.refresh_from_db()
    assert template.subject == "До правки"


@pytest.mark.django_db
def test_view_only_operator_cannot_test_send(view_only_operator):
    """`test-send` реально отправляет письмо — открытым его оставлять нельзя."""
    from notifications.models import EmailTemplate

    template = EmailTemplate.objects.create(key="lp_probe_send", subject="s", html_body="<p>x</p>")

    response = _api(view_only_operator).post(
        f"/api/v1/admin/email-templates/{template.pk}/test-send/", {"to": "x@test.uz"}, format="json"
    )

    assert response.status_code == 403


# ── Мастер компаний: вход в админку ≠ право создать арендатора ──────────────


@pytest.mark.django_db
def test_engineer_without_model_permission_cannot_open_company_wizard(client):
    """Член `system_engineers` без модельных прав проходил мастер до конца и ставил KYC."""
    engineer = CustomUser.objects.create_user(
        email="lp.engineer@test.uz", username="lp_engineer", password=PASSWORD, is_staff=True
    )
    engineer.groups.add(Group.objects.get(name=SYSTEM_ENGINEERS_GROUP))
    assert client.login(username=engineer.email, password=PASSWORD)

    response = client.get("/admin/accounts/company/wizard/")

    assert response.status_code == 403, "мастер компаний открыт без права `accounts.add_company`"


@pytest.mark.django_db
def test_engineer_with_add_company_permission_gets_in(client):
    """Запрет не должен закрыть путь тому, кому право выдали осознанно."""
    engineer = CustomUser.objects.create_user(
        email="lp.engineer2@test.uz", username="lp_engineer2", password=PASSWORD, is_staff=True
    )
    engineer.groups.add(Group.objects.get(name=SYSTEM_ENGINEERS_GROUP))
    engineer.user_permissions.add(Permission.objects.get(codename="add_company", content_type__app_label="accounts"))
    assert client.login(username=engineer.email, password=PASSWORD)

    response = client.get("/admin/accounts/company/wizard/")

    assert response.status_code == 200


# ── Форма пользователя: привилегированный блок только суперпользователю ─────


@pytest.mark.django_db
def test_privilege_fields_are_readonly_for_non_superuser():
    """Инженер сохранял себе `is_superuser` тремя кликами — право на модель ≠ право на все поля."""
    from django.contrib.admin.sites import AdminSite

    from accounts.admin import UserAdmin

    admin_instance = UserAdmin(CustomUser, AdminSite())

    class _Request:
        pass

    request = _Request()
    request.user = CustomUser.objects.create_user(
        email="lp.plain@test.uz", username="lp_plain", password=PASSWORD, is_staff=True
    )

    readonly = admin_instance.get_readonly_fields(request)

    for field in ("is_superuser", "is_staff", "groups", "user_permissions"):
        assert field in readonly, f"поле {field} редактируется не-суперпользователем"


@pytest.mark.django_db
def test_superuser_still_edits_privilege_fields():
    from django.contrib.admin.sites import AdminSite

    from accounts.admin import UserAdmin

    admin_instance = UserAdmin(CustomUser, AdminSite())

    class _Request:
        pass

    request = _Request()
    request.user = CustomUser.objects.create_user(
        email="lp.root@test.uz", username="lp_root", password=PASSWORD, is_staff=True, is_superuser=True
    )

    readonly = admin_instance.get_readonly_fields(request)

    assert "is_superuser" not in readonly
