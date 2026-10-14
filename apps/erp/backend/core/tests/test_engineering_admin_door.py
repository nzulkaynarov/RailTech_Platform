"""Дверь в инженерную админку: только суперпользователь или `system_engineers`.

Прогон глазами 20-08: сотрудник компании-арендатора с `is_staff` заходил на `/admin/`, видел
стартовый экран с оборотом ПЛАТФОРМЫ и скачивал `/admin/accounts/company/export/` — CSV на 42
компании с ИНН и банковскими счетами. Права на модели тут не помогали: django-import-export
закрывает правами только список объектов, а страницы `/export/` и `/import/` — нет, и сам
дашборд проверяет лишь `has_permission`.

Тесты держат три вещи разом: гейт входа, гейт выгрузки/загрузки и то, что сиды не воскрешают
флаг `is_staff` у бизнес-аккаунтов.
"""

import json
from pathlib import Path

import pytest
from django.conf import settings
from django.contrib.auth.models import Group
from django.test import Client

from accounts.models import CustomUser
from core.admin_site import SYSTEM_ENGINEERS_GROUP

PASSWORD = "Passw0rd!Door"


def _make_user(email, **flags):
    user = CustomUser.objects.create_user(email=email, username=email.split("@")[0], password=PASSWORD, **flags)
    return user


def _login(user):
    client = Client()
    assert client.login(username=user.email, password=PASSWORD), "форма логина не приняла пароль"
    return client


@pytest.mark.django_db
def test_staff_without_engineer_group_is_not_let_in():
    """Голого `is_staff` больше не хватает — именно так заходил арендатор."""
    user = _make_user("tenant.staff@example.com", is_staff=True)
    client = _login(user)

    response = client.get("/admin/", follow=True)

    # Django редиректит непрошедшего гейт на форму логина, а не показывает дашборд.
    assert response.redirect_chain, "пользователь остался на дашборде админки"
    assert "/admin/login/" in response.redirect_chain[-1][0]


@pytest.mark.django_db
def test_staff_without_engineer_group_cannot_export_or_import():
    """Страницы выгрузки и загрузки закрыты вместе с дверью."""
    user = _make_user("tenant.staff2@example.com", is_staff=True)
    client = _login(user)

    for path in ("/admin/accounts/company/export/", "/admin/accounts/customuser/import/"):
        response = client.get(path, follow=True)
        body = response.content.decode(errors="ignore")
        assert response.redirect_chain and "/admin/login/" in response.redirect_chain[-1][0], path
        assert "ИНН" not in body and "bank_account" not in body, f"{path} отдал данные компаний"


@pytest.mark.django_db
def test_engineer_group_member_gets_in():
    """Задуманный ADR-0001 путь работает: членство в группе открывает дверь."""
    user = _make_user("engineer@example.com", is_staff=True)
    user.groups.add(Group.objects.get(name=SYSTEM_ENGINEERS_GROUP))

    response = _login(user).get("/admin/")

    assert response.status_code == 200, "инженер не попал в админку"


@pytest.mark.django_db
def test_superuser_gets_in():
    """Не заперли сами себя: суперпользователь проходит без группы."""
    user = _make_user("root@example.com", is_staff=True, is_superuser=True)

    response = _login(user).get("/admin/")

    assert response.status_code == 200


@pytest.mark.django_db
def test_inactive_superuser_is_rejected():
    user = _make_user("frozen@example.com", is_staff=True, is_superuser=True)
    client = _login(user)
    CustomUser.objects.filter(pk=user.pk).update(is_active=False)

    response = client.get("/admin/", follow=True)

    assert response.redirect_chain, "заблокированный аккаунт остался внутри"


def test_import_export_permission_codes_are_set():
    """`view`/`change` вместо дефолтного `import_export.*` — иначе /export/ открыт всем staff."""
    assert settings.IMPORT_EXPORT_EXPORT_PERMISSION_CODE == "view"
    assert settings.IMPORT_EXPORT_IMPORT_PERMISSION_CODE == "change"


def test_user_resource_never_carries_privilege_fields():
    """XLSX не должен раздавать системную роль и доступ в админку."""
    from accounts.resources import UserResource

    user_fields = set(UserResource.Meta.fields)
    assert not user_fields & {"role", "is_staff", "is_superuser"}, user_fields


def test_seeds_do_not_hand_out_staff_flag():
    """Свежий стенд не должен рождаться с восемью «сотрудниками платформы»."""
    seed_path = Path(settings.BASE_DIR) / "core" / "data" / "seed_data.json"
    data = json.loads(seed_path.read_text(encoding="utf-8"))
    users = next(
        value
        for value in data.values()
        if isinstance(value, list) and value and isinstance(value[0], dict) and "is_staff" in value[0]
    )

    offenders = [user["email_default"] for user in users if user.get("is_staff") and not user.get("is_superuser")]

    assert offenders == [], f"сиды выдают is_staff бизнес-аккаунтам: {offenders}"
