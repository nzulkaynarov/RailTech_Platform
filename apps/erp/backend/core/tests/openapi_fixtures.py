"""Фикстуры и помощники сторожей «OpenAPI `/api/v1` = поведение кода» (D2-0): администратор, своя компания, сверка ответа.

Подключаются в тестовых файлах `test_openapi_*_conformance.py` явным импортом (в `core/tests` нет conftest).
"""

import pytest
from rest_framework.test import APIClient

from accounts.models import Company, CompanyMember, CustomUser, WorkspaceRole
from accounts.testing import make_own_company
from core.tests.openapi_internal import request_fields_missing, response_errors

API = "/api/v1/"


@pytest.fixture
def admin():
    user = CustomUser.objects.create_user(
        email="admin@d2-0.test", username="admin@d2-0.test", password="pw", is_superuser=True, is_active=True
    )
    client = APIClient()
    client.force_authenticate(user)
    client.user = user
    return client


@pytest.fixture
def company(admin):
    """Своя компания ERP: SUPPLIER + участник (так её находит `core.tenant.own_company`)."""
    own = make_own_company(Company.objects.create(name="Контрактная компания", inn="300000099"))
    role = WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Владелец", "sort_order": 1})[0]
    CompanyMember.objects.create(user=admin.user, company=own, role=role, is_primary=True, is_active=True)
    return own


def conforms(response, template, method, *, status=None):
    """Статус и тело ответа совпадают с операцией `template` выгрузки."""
    if status is not None:
        assert response.status_code == status, (response.status_code, getattr(response, "data", None))
    errors = response_errors(response, template, method)
    assert not errors, f"{method.upper()} {template} → {response.status_code}: " + "; ".join(errors)


def sends(template, method, body):
    """Поля тела, которые шлёт BFF, описаны схемой запроса."""
    missing = request_fields_missing(template, method, body)
    assert not missing, f"{method.upper()} {template}: схема запроса не содержит полей {missing}"
