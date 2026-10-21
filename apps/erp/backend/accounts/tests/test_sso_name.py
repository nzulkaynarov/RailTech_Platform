"""FIX-64 / N-03: SSO-вход делит имя из токена на first_name и last_name — «Имя Фамилия» один раз.

Раньше `sso.py` писал claim `name` целиком в `first_name` поверх деления провижининга, и `get_full_name()`
давал «Имя Фамилия Фамилия» в публичной КП, PDF, подписях договора и письмах. Одно правило деления —
`split_full_name` (то же, что у `POST /users/provision`); одно слово — только имя.
"""

import importlib
import uuid

import pytest
from django.apps import apps as django_apps
from django.core.cache import cache
from integration.models import CrmUserMapping
from rest_framework.test import APIClient

from accounts.models import Company, CompanyType, CustomUser, WorkspaceRole
from accounts.tests.test_sso import SSO_SECRET_PRIMARY, make_sso_jwt  # noqa: F401

pytestmark = pytest.mark.django_db

SERVICE_TOKEN = "test-crm-to-erp-token"


@pytest.fixture(autouse=True)
def _sso_settings(settings):
    settings.PLATFORM_SSO_SECRET = [SSO_SECRET_PRIMARY]
    settings.PLATFORM_SSO_ENABLED = True
    settings.CRM_FRONTEND_URL = "http://crm.localhost"
    settings.SERVICE_TOKEN_CRM_TO_ERP = [SERVICE_TOKEN]
    cache.clear()


def _user(first="", last="", crm_user_id=42, email="staff@example.com"):
    user = CustomUser.objects.create(
        username=email, email=email, first_name=first, last_name=last, is_staff=True, is_active=True
    )
    CrmUserMapping.objects.create(crm_user_id=crm_user_id, user=user)
    return user


def _exchange(name, crm_user_id=42, email="staff@example.com"):
    token = make_sso_jwt(sub=str(crm_user_id), email=email, name=name)
    response = APIClient().post("/api/v1/auth/sso/exchange/", data={"token": token}, format="json")
    assert response.status_code == 200, response.content
    return response


def test_exchange_splits_full_name_into_first_and_last():
    user = _user()
    _exchange("FIX-64 Расчётчик")
    user.refresh_from_db()
    assert (user.first_name, user.last_name) == ("FIX-64", "Расчётчик")
    assert user.get_full_name() == "FIX-64 Расчётчик"


def test_exchange_does_not_duplicate_last_name_over_provisioned_profile():
    """Провижининг уже разложил имя; следующий вход не должен склеить его обратно (баг N-03)."""
    user = _user(first="FIX-64", last="Расчётчик")
    _exchange("FIX-64 Расчётчик")
    user.refresh_from_db()
    assert (user.first_name, user.last_name) == ("FIX-64", "Расчётчик")
    assert user.get_full_name() == "FIX-64 Расчётчик"


def test_exchange_repairs_already_broken_name_and_is_stable():
    user = _user(first="FIX-64 Расчётчик", last="Расчётчик")
    _exchange("FIX-64 Расчётчик")
    _exchange("FIX-64 Расчётчик")
    user.refresh_from_db()
    assert (user.first_name, user.last_name) == ("FIX-64", "Расчётчик")


def test_exchange_single_word_name_goes_to_first_name_only():
    user = _user(first="Старое", last="Фамилия")
    _exchange("Мастер")
    user.refresh_from_db()
    assert (user.first_name, user.last_name) == ("Мастер", "")


def test_exchange_multiword_last_name_keeps_remainder():
    user = _user()
    _exchange("Иван Петров Сидоров")
    user.refresh_from_db()
    assert (user.first_name, user.last_name) == ("Иван", "Петров Сидоров")


def test_provision_then_sso_gives_same_full_name_once():
    """Сквозной путь: CRM выдаёт доступ (provision) → сотрудник входит по SSO — имя то же, без дублей."""
    own = Company.objects.create(name="Own Co", inn="OWN-FIX64")
    own.types.add(CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier"})[0])
    WorkspaceRole.objects.get_or_create(code="MEMBER", defaults={"name": "Member", "sort_order": 10})
    api = APIClient()
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {SERVICE_TOKEN}")
    from django.test import override_settings

    with override_settings(OWN_COMPANY_ID=own.pk):
        resp = api.post(
            "/api/integration/v1/users/provision",
            {
                "crm_user_id": 7064,
                "email": "fix64.staff@own.test",
                "name": "FIX-64 Расчётчик",
                "role": "backoffice",
                "permissions": ["quote.build"],
                "is_active": True,
            },
            format="json",
            HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
        )
    assert resp.status_code == 201, resp.content
    user = CustomUser.objects.get(email="fix64.staff@own.test")
    assert (user.first_name, user.last_name) == ("FIX-64", "Расчётчик")

    _exchange("FIX-64 Расчётчик", crm_user_id=7064, email="fix64.staff@own.test")
    user.refresh_from_db()
    assert user.get_full_name() == "FIX-64 Расчётчик"


# ── Миграция данных: уже созданные пользователи ──────────────────────────────

MIGRATION = "accounts.migrations.0008_split_sso_full_names"


def _run_migration():
    importlib.import_module(MIGRATION).split_sso_full_names(django_apps, None)


def test_data_migration_repairs_duplicated_last_name():
    broken = _user(first="FIX-50b Расчётчик", last="Расчётчик", crm_user_id=1, email="a@example.com")
    _run_migration()
    broken.refresh_from_db()
    assert (broken.first_name, broken.last_name) == ("FIX-50b", "Расчётчик")


def test_data_migration_splits_full_name_of_crm_user_without_last_name():
    legacy = _user(first="Иван Петров", last="", crm_user_id=2, email="b@example.com")
    _run_migration()
    legacy.refresh_from_db()
    assert (legacy.first_name, legacy.last_name) == ("Иван", "Петров")


def test_data_migration_leaves_healthy_and_foreign_profiles_alone_and_is_idempotent():
    healthy = _user(first="Иван", last="Петров", crm_user_id=3, email="c@example.com")
    single = _user(first="Мастер", last="", crm_user_id=4, email="d@example.com")
    # Не сотрудник CRM (нет сопоставления): имя с пробелом без фамилии — не наше, не трогаем.
    foreign = CustomUser.objects.create(username="e@example.com", email="e@example.com", first_name="Анна Мария")
    broken = _user(first="Ли Ли", last="Ли", crm_user_id=5, email="f@example.com")
    _run_migration()
    _run_migration()
    for user, expected in (
        (healthy, ("Иван", "Петров")),
        (single, ("Мастер", "")),
        (foreign, ("Анна Мария", "")),
        (broken, ("Ли", "Ли")),
    ):
        user.refresh_from_db()
        assert (user.first_name, user.last_name) == expected
