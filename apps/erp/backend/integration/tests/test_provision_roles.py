"""FIX-55 / D-07, D-12: провижининг из CRM управляет только своей ролью и не затирает профиль.

Раньше `member.company_roles.set([crm_role])` при каждом провижининге стирал роли, выданные в ERP вручную
(«Настройки → Команда»), а `first_name=name` клал всё имя в first_name и затирал правки профиля.
Теперь: управляемая роль «CRM Sync: <e-mail>» создаётся/обновляется/добавляется через add и снимается при
отзыве доступа; ручные роли не трогаются. Имя делится на first/last только при создании или если обе части пусты.
"""

import uuid

import pytest
from rest_framework.test import APIClient

from accounts.models import Company, CompanyMember, CompanyRole, CompanyType, CustomUser, WorkspaceRole

pytestmark = pytest.mark.django_db

SERVICE_TOKEN = "test-crm-to-erp-token"


@pytest.fixture(autouse=True)
def own_company(settings):
    settings.SERVICE_TOKEN_CRM_TO_ERP = [SERVICE_TOKEN]
    WorkspaceRole.objects.get_or_create(code="MEMBER", defaults={"name": "Member", "sort_order": 10})
    company = Company.objects.create(name="Own Co", inn="OWN-PROV")
    company.types.add(CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier"})[0])
    settings.OWN_COMPANY_ID = company.pk
    return company


@pytest.fixture
def client():
    api = APIClient()
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {SERVICE_TOKEN}")
    return api


def _provision(client, crm_user_id=7001, email="staff@own.test", name="Иван Петров", permissions=("quote.build",)):
    return client.post(
        "/api/integration/v1/users/provision",
        {
            "crm_user_id": crm_user_id,
            "email": email,
            "name": name,
            "role": "backoffice",
            "permissions": list(permissions),
            "is_active": True,
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
    )


def _member(email="staff@own.test"):
    return CompanyMember.objects.get(user__email=email)


def test_first_provision_creates_managed_role(client, own_company):
    assert _provision(client).status_code == 201
    roles = list(_member().company_roles.all())
    assert [role.name for role in roles] == ["CRM Sync: staff@own.test"]
    assert roles[0].managed_by_crm is True
    assert roles[0].permissions == ["quote.build"]


def test_reprovision_keeps_manually_assigned_roles(client, own_company):
    """D-07: роль, выданная в ERP вручную, переживает повторный провижининг."""
    _provision(client)
    manual = CompanyRole.objects.create(company=own_company, name="Склад (вручную)", permissions=["supply.manage"])
    _member().company_roles.add(manual)

    _provision(client, permissions=("quote.build", "quote.send"))

    names = set(_member().company_roles.values_list("name", flat=True))
    assert names == {"CRM Sync: staff@own.test", "Склад (вручную)"}
    sync_role = CompanyRole.objects.get(name="CRM Sync: staff@own.test")
    assert sync_role.permissions == ["quote.build", "quote.send"], "права управляемой роли обновляются"
    assert CompanyRole.objects.get(pk=manual.pk).permissions == ["supply.manage"]


def test_reprovision_does_not_duplicate_managed_role(client, own_company):
    _provision(client)
    _provision(client)
    assert _member().company_roles.count() == 1
    assert CompanyRole.objects.filter(name="CRM Sync: staff@own.test").count() == 1


def test_revoke_removes_only_the_managed_role(client, own_company):
    _provision(client)
    manual = CompanyRole.objects.create(company=own_company, name="Финансы (вручную)", permissions=["finance.invoice"])
    _member().company_roles.add(manual)

    response = client.delete("/api/integration/v1/users/7001/sessions")

    assert response.status_code == 204
    assert list(_member().company_roles.values_list("name", flat=True)) == ["Финансы (вручную)"]
    assert CustomUser.objects.get(email="staff@own.test").is_active is False


def test_reprovision_after_revoke_restores_managed_role(client, own_company):
    _provision(client)
    client.delete("/api/integration/v1/users/7001/sessions")
    _provision(client)
    assert list(_member().company_roles.values_list("name", flat=True)) == ["CRM Sync: staff@own.test"]


def test_name_is_split_into_first_and_last_on_create(client):
    _provision(client, name="Иван Петров")
    user = CustomUser.objects.get(email="staff@own.test")
    assert (user.first_name, user.last_name) == ("Иван", "Петров")


def test_single_word_name_goes_to_first_name(client):
    _provision(client, name="Иван")
    user = CustomUser.objects.get(email="staff@own.test")
    assert (user.first_name, user.last_name) == ("Иван", "")


def test_resync_does_not_overwrite_profile_edited_in_erp(client):
    """D-12: имя/фамилия, исправленные в ERP, не затираются при каждой синхронизации."""
    _provision(client, name="Иван Петров")
    CustomUser.objects.filter(email="staff@own.test").update(first_name="Иван", last_name="Петров-Сидоров")

    _provision(client, name="Иван Петров")

    user = CustomUser.objects.get(email="staff@own.test")
    assert (user.first_name, user.last_name) == ("Иван", "Петров-Сидоров")


def test_resync_fills_empty_profile(client):
    _provision(client, name="Иван Петров")
    CustomUser.objects.filter(email="staff@own.test").update(first_name="", last_name="")

    _provision(client, name="Пётр Сидоров")

    user = CustomUser.objects.get(email="staff@own.test")
    assert (user.first_name, user.last_name) == ("Пётр", "Сидоров")
