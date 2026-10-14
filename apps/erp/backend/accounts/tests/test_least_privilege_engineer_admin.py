"""Наименьшие привилегии в инженерной админке (Django Unfold остаётся инженерам — ARCHITECTURE §7).

Прогон 20-08 нашёл класс «право нарисовано в меню, но за скрытой дверью ничего не стоит»:
член инженерной группы без единого модельного права создавал арендатора через мастер;
инженер с правом на модель пользователя сохранял себе `is_superuser`.

Операторская часть этого файла (роль оператора «только просмотр») удалена в M1-ERP-02 волна 1a
вместе с операторской плоскостью: администратор ERP = `is_superuser`.
"""

import pytest
from django.contrib.auth.models import Group, Permission

from accounts.models import CustomUser
from core.admin_site import SYSTEM_ENGINEERS_GROUP

PASSWORD = "Passw0rd!LP"


# ── Мастер компаний: вход в админку ≠ право создать арендатора ──────────────


@pytest.mark.django_db
def test_engineer_without_model_permission_cannot_open_company_wizard(client):
    """Член `system_engineers` без модельных прав проходил мастер до конца и создавал арендатора."""
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
    from accounts.models import Company

    engineer = CustomUser.objects.create_user(
        email="lp.engineer2@test.uz", username="lp_engineer2", password=PASSWORD, is_staff=True
    )
    engineer.groups.add(Group.objects.get(name=SYSTEM_ENGINEERS_GROUP))
    engineer.user_permissions.add(
        Permission.objects.get(codename="add_company", content_type__app_label=Company._meta.app_label)
    )
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
