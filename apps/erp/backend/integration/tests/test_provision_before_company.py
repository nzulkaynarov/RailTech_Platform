"""FIX-P1-2 / QA-P1-D-2: сотрудники, которых CRM провижинила ДО создания своей компании, становятся её участниками.

На чистой установке своей компании нет, пока администратор не пройдёт мастер первого запуска (FIX-65). Провижининг
до этого сохраняет пользователя и сопоставление, но члена компании создавать некуда; раньше сотрудник привязывался
только следующим провижинингом (правка ролей в CRM). Теперь `create_own_company` в той же транзакции привязывает
активных сотрудников с ролями из последнего провижининга (`CrmUserMapping.provision_snapshot`).
"""

import uuid

import pytest
from integration.models import CrmUserMapping
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import CompanyMember, CustomUser, WorkspaceRole
from accounts.services.own_company_setup import create_own_company
from accounts.services.permissions import member_has_permission, sees_all_deals
from core.tenant import own_company_id
from crm.models import ActivityLog, Deal, DealStage

pytestmark = pytest.mark.django_db

SERVICE_TOKEN = "test-crm-to-erp-token"
ATTACH_ACTION = "Сотрудники из CRM привязаны к своей компании"
COMPANY = {"name": "ООО Рейл", "inn": "123456789"}


@pytest.fixture(autouse=True)
def lookups(settings):
    settings.SERVICE_TOKEN_CRM_TO_ERP = [SERVICE_TOKEN]
    settings.OWN_COMPANY_ID = None
    WorkspaceRole.objects.get_or_create(code="MEMBER", defaults={"name": "Member", "sort_order": 10})
    WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 1})
    DealStage.objects.get_or_create(code="DRAFT", defaults={"name": "DRAFT", "sort_order": 10})


@pytest.fixture
def crm():
    api = APIClient()
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {SERVICE_TOKEN}")
    return api


@pytest.fixture
def admin():
    return CustomUser.objects.create_superuser(email="root@erp.test", username="root@erp.test", password="x")


def _provision(crm, crm_user_id, email, *, role="backoffice", permissions=(), role_codes=None, is_active=True):
    body = {
        "crm_user_id": crm_user_id,
        "email": email,
        "name": "Иван Петров",
        "role": role,
        "permissions": list(permissions),
        "is_active": is_active,
    }
    if role_codes is not None:
        body["role_codes"] = role_codes
    response = crm.post(
        "/api/integration/v1/users/provision", body, format="json", HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4())
    )
    assert response.status_code in (200, 201), response.content
    return CustomUser.objects.get(email=email)


def _create_company(admin):
    company, error = create_own_company(admin, COMPANY)
    assert error is None, error
    return company


def _deals_as(user):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
    body = client.get("/api/v1/crm/deals/").json()
    rows = body["results"] if isinstance(body, dict) and "results" in body else body
    return {row["id"] for row in rows}


def _role_names(member):
    return set(member.company_roles.values_list("name", flat=True))


def test_provisioned_before_company_becomes_member_and_sees_deals(crm, admin):
    manager = _provision(crm, 1, "manager@own.test", permissions=["deal.manage", "quote.build"], role_codes=["FINANCE"])
    assert not CompanyMember.objects.filter(user=manager).exists(), "компании ещё нет — привязывать некуда"
    deal = Deal.objects.create(title="Сделка", company=None, stage=DealStage.objects.get(code="DRAFT"))

    company = _create_company(admin)

    assert own_company_id() == company.pk
    member = CompanyMember.objects.get(user=manager, company=company)
    assert member.is_active
    assert "CRM Sync: manager@own.test" in _role_names(member)
    assert set(member.company_roles.exclude(code="").values_list("code", flat=True)) == {"FINANCE"}
    assert member_has_permission(manager, company.pk, "deal.manage")
    assert member_has_permission(manager, company.pk, "finance.invoice"), "права системной роли — по шаблону ERP"
    assert not member_has_permission(manager, company.pk, "supplier.manage")
    # Те же права, которыми ERP фильтрует сделки: сотрудник компании-владельца видит их все.
    assert sees_all_deals(manager)
    assert _deals_as(manager) == {deal.id}


def test_superuser_from_crm_is_attached_without_backoffice_roles(crm, admin):
    boss = _provision(crm, 2, "boss@own.test", role="admin")
    company = _create_company(admin)

    member = CompanyMember.objects.get(user=boss, company=company)
    assert boss.is_superuser
    assert member.company_roles.count() == 0, "суперпользователю роли бэк-офиса не нужны"


def test_creator_who_is_also_provisioned_keeps_owner_position(crm, admin):
    CrmUserMapping.objects.create(
        crm_user_id=3, user=admin, provision_snapshot={"role": "admin", "permissions": [], "role_codes": []}
    )
    company = _create_company(admin)

    members = CompanyMember.objects.filter(user=admin, company=company)
    assert members.count() == 1
    assert members.get().role.code == "OWNER"


def test_deactivated_in_crm_before_company_is_not_attached(crm, admin):
    off = _provision(crm, 4, "off@own.test", permissions=["deal.manage"], is_active=False)
    revoked = _provision(crm, 5, "revoked@own.test", permissions=["deal.manage"])
    assert crm.delete("/api/integration/v1/users/5/sessions").status_code in (200, 204)

    company = _create_company(admin)

    assert not CompanyMember.objects.filter(user__in=[off, revoked], company=company).exists()


def test_reattach_is_idempotent(crm, admin):
    manager = _provision(crm, 6, "again@own.test", permissions=["deal.manage"], role_codes=["FINANCE"])
    company = _create_company(admin)
    member = CompanyMember.objects.get(user=manager, company=company)
    roles_before = set(member.company_roles.values_list("pk", flat=True))

    from integration.services.provision import attach_provisioned_users

    attach_provisioned_users(company)
    attach_provisioned_users(company)

    assert CompanyMember.objects.filter(user=manager, company=company).count() == 1
    assert set(CompanyMember.objects.get(pk=member.pk).company_roles.values_list("pk", flat=True)) == roles_before
    assert member.company_roles.filter(name="CRM Sync: again@own.test").count() == 1
    # Повторное создание своей компании отклоняется — ничего не дублируется.
    again, error = create_own_company(admin, COMPANY)
    assert again is None and error == "OWN_COMPANY_ALREADY_EXISTS"
    assert CompanyMember.objects.filter(user=manager).count() == 1


def test_attach_is_audited(crm, admin):
    manager = _provision(crm, 7, "audit@own.test", permissions=["deal.manage"])
    company = _create_company(admin)

    entry = ActivityLog.objects.get(action=ATTACH_ACTION, entity_id=company.pk)
    assert entry.after_data == {"count": 1, "erp_user_ids": [manager.pk]}
    assert entry.user == admin


def test_no_provisioned_users_means_no_audit_entry(admin):
    company = _create_company(admin)
    assert not ActivityLog.objects.filter(action=ATTACH_ACTION, entity_id=company.pk).exists()


def test_legacy_mapping_without_snapshot_gets_minimum_rights(crm, admin):
    legacy = _provision(crm, 8, "legacy@own.test", permissions=["deal.manage"])
    CrmUserMapping.objects.filter(crm_user_id=8).update(provision_snapshot=None)

    company = _create_company(admin)

    member = CompanyMember.objects.get(user=legacy, company=company)
    assert not member_has_permission(legacy, company.pk, "deal.manage"), "прав из запроса не сохранено — минимум"
    assert set(member.company_roles.exclude(code="")) == set()
    assert sees_all_deals(legacy)


def test_provision_after_company_works_as_before(crm, admin):
    company = _create_company(admin)

    manager = _provision(crm, 9, "late@own.test", permissions=["deal.manage"], role_codes=["FINANCE"])

    member = CompanyMember.objects.get(user=manager, company=company)
    assert member_has_permission(manager, company.pk, "deal.manage")
    assert set(member.company_roles.exclude(code="").values_list("code", flat=True)) == {"FINANCE"}
    assert CrmUserMapping.objects.get(crm_user_id=9).provision_snapshot == {
        "role": "backoffice",
        "permissions": ["deal.manage"],
        "role_codes": ["FINANCE"],
    }


def test_reprovision_updates_snapshot_used_for_attach(crm, admin):
    _provision(crm, 10, "edit@own.test", permissions=["deal.manage"])
    manager = _provision(crm, 10, "edit@own.test", permissions=["quote.build"], role_codes=[])

    company = _create_company(admin)

    assert member_has_permission(manager, company.pk, "quote.build")
    assert not member_has_permission(manager, company.pk, "deal.manage")
