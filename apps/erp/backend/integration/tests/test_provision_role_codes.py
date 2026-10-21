"""FIX-63 / D-10, Q-FIX50-1 (1): системные роли ERP из CRM — `role_codes` в `POST /users/provision`.

ERP добавляет пришедшие системные роли и помечает их «выдана из CRM»; следующий провижининг снимает только
помеченные, которых в `role_codes` больше нет. Ручные роли («Настройки → Команда») и роль «CRM Sync: <e-mail>» не
затрагиваются. Поля `role_codes` нет (старый CRM) — системные роли не трогаются. Отзыв доступа снимает и роли из CRM.
"""

import uuid

import pytest
from rest_framework.test import APIClient

from accounts.constants import BackofficeRoleCode
from accounts.models import Company, CompanyMember, CompanyRole, CompanyType, CustomUser, WorkspaceRole
from accounts.services.permissions import member_has_permission
from accounts.services.roles import ensure_default_company_roles

pytestmark = pytest.mark.django_db

SERVICE_TOKEN = "test-crm-to-erp-token"
EMAIL = "staff63@own.test"


@pytest.fixture(autouse=True)
def own_company(settings):
    settings.SERVICE_TOKEN_CRM_TO_ERP = [SERVICE_TOKEN]
    WorkspaceRole.objects.get_or_create(code="MEMBER", defaults={"name": "Member", "sort_order": 10})
    company = Company.objects.create(name="Own Co", inn="OWN-FIX63")
    company.types.add(CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier"})[0])
    settings.OWN_COMPANY_ID = company.pk
    return company


@pytest.fixture
def client():
    api = APIClient()
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {SERVICE_TOKEN}")
    return api


_ABSENT = object()


def _provision(client, role_codes=_ABSENT, role="backoffice", permissions=("quote.build",), crm_user_id=6301):
    body = {
        "crm_user_id": crm_user_id,
        "email": EMAIL,
        "name": "Иван Петров",
        "role": role,
        "permissions": list(permissions),
        "is_active": True,
    }
    if role_codes is not _ABSENT:
        body["role_codes"] = role_codes
    return client.post(
        "/api/integration/v1/users/provision", body, format="json", HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4())
    )


def _member():
    return CompanyMember.objects.get(user__email=EMAIL)


def _role_names(member=None):
    return set((member or _member()).company_roles.values_list("name", flat=True))


def _codes(member=None):
    return set((member or _member()).company_roles.exclude(code="").values_list("code", flat=True))


def test_grant_system_roles_from_crm(client):
    response = _provision(client, ["CALCULATION", "FINANCE"])

    assert response.status_code == 201, response.content
    member = _member()
    assert _codes(member) == {"CALCULATION", "FINANCE"}
    assert "CRM Sync: staff63@own.test" in _role_names(member), "своя роль CRM Sync остаётся"
    # права системных ролей — по шаблону ERP, не из запроса
    assert member_has_permission(member.user, member.company_id, "finance.invoice")
    assert member_has_permission(member.user, member.company_id, "contract.manage")
    assert not member_has_permission(member.user, member.company_id, "catalog.manage")


def test_change_roles_adds_and_removes_only_what_crm_granted(client):
    _provision(client, ["CALCULATION", "FINANCE"])

    _provision(client, ["FINANCE", "HEAD"])

    assert _codes() == {"FINANCE", "HEAD"}, "CALCULATION снята, HEAD добавлена, FINANCE осталась"


def test_empty_role_codes_removes_every_role_granted_from_crm(client):
    _provision(client, ["CALCULATION", "HEAD"])

    _provision(client, [])

    assert _codes() == set()
    assert _role_names() == {"CRM Sync: staff63@own.test"}


def test_manual_roles_are_not_touched(client, own_company):
    """FIX-55 сохраняется: роли «Команды», не пришедшие из CRM, не затираются — ни системные, ни свои."""
    _provision(client, ["CALCULATION"])
    manual_custom = CompanyRole.objects.create(
        company=own_company, name="Склад (вручную)", permissions=["supply.manage"]
    )
    manual_system = ensure_default_company_roles(own_company)[BackofficeRoleCode.FULFILLMENT]
    _member().company_roles.add(manual_custom, manual_system)

    _provision(client, ["FINANCE"])
    assert {"Склад (вручную)", manual_system.name} <= _role_names()
    assert _codes() == {"FINANCE", "FULFILLMENT"}, "CALCULATION из CRM снята, ручная FULFILLMENT осталась"

    _provision(client, [])
    assert _role_names() == {"CRM Sync: staff63@own.test", "Склад (вручную)", manual_system.name}


def test_role_already_assigned_manually_is_not_taken_over_by_crm(client, own_company):
    """Системная роль, выданная в ERP вручную до CRM, не помечается «из CRM» и не снимается, когда CRM её убирает."""
    _provision(client)
    head = ensure_default_company_roles(own_company)[BackofficeRoleCode.HEAD]
    _member().company_roles.add(head)

    _provision(client, ["HEAD"])
    _provision(client, [])

    assert "HEAD" in _codes()


def test_role_removed_manually_in_team_comes_back_while_crm_still_grants_it(client):
    _provision(client, ["FINANCE"])
    member = _member()
    member.company_roles.set(member.company_roles.exclude(code="FINANCE"))
    assert _codes(member) == set()

    _provision(client, ["FINANCE"])

    assert _codes() == {"FINANCE"}, "CRM — источник истины по выданным из неё ролям"


def test_without_role_codes_system_roles_stay(client, own_company):
    """Старый CRM не шлёт `role_codes`: выданное (из CRM и вручную) не меняется."""
    _provision(client, ["CALCULATION"])
    manual = ensure_default_company_roles(own_company)[BackofficeRoleCode.VIEWER]
    _member().company_roles.add(manual)

    response = _provision(client, permissions=("quote.build", "quote.send"))

    assert response.status_code == 200
    assert _codes() == {"CALCULATION", "VIEWER"}
    assert CompanyRole.objects.get(name="CRM Sync: staff63@own.test").permissions == ["quote.build", "quote.send"]


def test_without_role_codes_on_first_provision_no_system_roles(client):
    assert _provision(client).status_code == 201
    assert _codes() == set()


def test_unknown_role_code_is_422_and_changes_nothing(client):
    _provision(client, ["CALCULATION"])

    for bad in (["ROOT"], ["CALCULATION", "admin"], "HEAD", [1]):
        response = _provision(client, bad)
        assert response.status_code == 422, (bad, response.content)
        assert response.json() == {"detail": "VALIDATION_ERROR"}

    assert _codes() == {"CALCULATION"}


def test_duplicate_role_codes_are_tolerated(client):
    """Читатель терпим: дубль в `role_codes` схлопывается, а не роняет провижининг."""
    assert _provision(client, ["HEAD", "HEAD"]).status_code == 201
    assert _member().company_roles.filter(code="HEAD").count() == 1


def test_revoke_removes_roles_granted_from_crm_and_keeps_manual_ones(client, own_company):
    _provision(client, ["CALCULATION", "FINANCE"])
    manual = CompanyRole.objects.create(company=own_company, name="Склад (вручную)", permissions=["supply.manage"])
    manual_system = ensure_default_company_roles(own_company)[BackofficeRoleCode.FULFILLMENT]
    _member().company_roles.add(manual, manual_system)

    response = client.delete("/api/integration/v1/users/6301/sessions")

    assert response.status_code == 204
    assert _role_names() == {"Склад (вручную)", manual_system.name}
    assert CustomUser.objects.get(email=EMAIL).is_active is False


def test_reprovision_after_revoke_gives_roles_back(client):
    _provision(client, ["HEAD"])
    client.delete("/api/integration/v1/users/6301/sessions")
    assert _codes() == set()

    _provision(client, ["HEAD"])

    assert _codes() == {"HEAD"}


def test_admin_role_drops_granted_system_roles_but_keeps_manual(client, own_company):
    """CRM `admin` = суперпользователь: роли из CRM ему не нужны и снимаются, ручные остаются."""
    _provision(client, ["CALCULATION"])
    manual = ensure_default_company_roles(own_company)[BackofficeRoleCode.FULFILLMENT]
    _member().company_roles.add(manual)

    response = _provision(client, ["HEAD"], role="admin")

    assert response.status_code == 200
    assert CustomUser.objects.get(email=EMAIL).is_superuser is True
    assert _codes() == {"FULFILLMENT"}


def test_back_from_admin_to_backoffice_roles_follow_role_codes(client):
    _provision(client, ["HEAD"], role="admin")
    _provision(client, ["FINANCE"], role="backoffice")
    assert _codes() == {"FINANCE"}


def test_system_roles_are_shared_rows_not_copies(client, own_company):
    """Роль CRM — та самая системная роль компании (права по шаблону ERP), а не её копия."""
    _provision(client, ["HEAD"])
    head = CompanyRole.objects.get(company=own_company, code="HEAD")
    assert head.is_system and head.managed_by_crm is False
    assert CompanyRole.objects.filter(company=own_company, code="HEAD").count() == 1
    assert _member().company_roles.get(code="HEAD").pk == head.pk
