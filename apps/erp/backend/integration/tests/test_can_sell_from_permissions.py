"""СОТР-1: `can_sell` — кому идут уведомления продавца по сделкам — выставляется из прав сотрудника при провижининге,
а не остаётся «да» у всех; разовая миграция данных чинит существующих участников и обратима."""

import importlib
import uuid

import pytest
from django.apps import apps as django_apps
from integration.models import CrmUserMapping
from rest_framework.test import APIClient

from accounts.models import CompanyMember, CustomUser, WorkspaceRole
from accounts.services.own_company_setup import create_own_company
from crm.models import DealStage
from crm.services.deal_notifications import seller_team_user_ids

pytestmark = pytest.mark.django_db

SERVICE_TOKEN = "test-crm-to-erp-token"
# Права из каталога Платформы (platform-rbac.yaml) для шаблонов: «Менеджер» (`crm.clients` + `erp.calc`),
# «Снабженец» (`erp.calc.goods`), «Инженер» (`erp.calc.services`), «Бухгалтер» (`eds.payments`-финансы).
SELLER = ["deal.manage", "quote.send", "quote.build", "quote.edit_pricing"]
CALC_ONLY = ["deal.manage", "quote.build", "quote.edit_pricing"]  # `erp.calc: full` без `crm.clients`
SUPPLY = ["quote.build", "quote.visa_goods"]
ENGINEER = ["quote.build", "quote.visa_services"]
ACCOUNTANT = ["finance.view", "finance.invoice", "finance.payment"]
migration = importlib.import_module("integration.migrations.0015_can_sell_from_permissions")


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
def company(settings):
    root = CustomUser.objects.create_superuser(email="root@erp.test", username="root@erp.test", password="x")
    created, error = create_own_company(root, {"name": "ООО Рейл", "inn": "123456789"})
    assert error is None, error
    settings.OWN_COMPANY_ID = created.pk
    return created


def provision(crm, crm_user_id, email, *, role="backoffice", permissions=()):
    body = {
        "crm_user_id": crm_user_id,
        "email": email,
        "name": "Иван Петров",
        "role": role,
        "permissions": list(permissions),
        "is_active": True,
    }
    response = crm.post(
        "/api/integration/v1/users/provision", body, format="json", HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4())
    )
    assert response.status_code in (200, 201), response.content
    return CustomUser.objects.get(email=email)


def member_of(user, company):
    return CompanyMember.objects.get(user=user, company=company)


def test_only_holders_of_deal_rights_are_sellers_at_provisioning(crm, company):
    manager = provision(crm, 11, "manager@own.test", permissions=SELLER)
    accountant = provision(crm, 12, "accountant@own.test", permissions=ACCOUNTANT)
    supplier = provision(crm, 13, "supply@own.test", permissions=SUPPLY)
    engineer = provision(crm, 15, "engineer@own.test", permissions=ENGINEER)
    calc = provision(crm, 16, "calc@own.test", permissions=CALC_ONLY)
    boss = provision(crm, 14, "boss@own.test", role="admin", permissions=SELLER)

    assert member_of(manager, company).can_sell is True
    assert member_of(accountant, company).can_sell is False
    assert member_of(supplier, company).can_sell is False
    assert member_of(engineer, company).can_sell is False
    assert member_of(calc, company).can_sell is False, "расчёт без права отправлять КП клиенту — не продавец"
    assert member_of(boss, company).can_sell is False, "администратор (суперпользователь) — не продавец"
    recipients = set(seller_team_user_ids(deal=None))
    assert manager.pk in recipients
    assert not {accountant.pk, supplier.pk, engineer.pk, calc.pk, boss.pk} & recipients


def test_reprovisioning_with_the_same_rights_keeps_the_owners_manual_choice(crm, company):
    manager = provision(crm, 21, "m@own.test", permissions=SELLER)
    CompanyMember.objects.filter(user=manager, company=company).update(can_sell=False)  # владелец выключил в «Команде»
    provision(crm, 21, "m@own.test", permissions=SELLER)
    assert member_of(manager, company).can_sell is False


def test_a_change_of_deal_rights_recomputes_can_sell(crm, company):
    person = provision(crm, 31, "p@own.test", permissions=["finance.view"])
    assert member_of(person, company).can_sell is False
    provision(crm, 31, "p@own.test", permissions=SELLER)  # получил право вести сделки
    assert member_of(person, company).can_sell is True
    provision(crm, 31, "p@own.test", permissions=["finance.view"])  # и лишился
    assert member_of(person, company).can_sell is False


def test_data_migration_fixes_existing_members_and_reverses(crm, company):
    manager = provision(crm, 41, "m41@own.test", permissions=SELLER)
    accountant = provision(crm, 42, "a42@own.test", permissions=["finance.view"])
    boss = provision(crm, 43, "b43@own.test", role="admin")
    # Как до исправления: у всех «да».
    CompanyMember.objects.filter(user__in=[manager, accountant, boss]).update(can_sell=True)
    CrmUserMapping.objects.filter(crm_user_id=44).delete()

    migration.forwards(django_apps, None)
    assert [member_of(u, company).can_sell for u in (manager, accountant, boss)] == [True, False, False]

    migration.backwards(django_apps, None)
    assert [member_of(u, company).can_sell for u in (manager, accountant, boss)] == [True, True, True]


def test_permissions_used_here_exist_in_the_erp_catalog():
    from accounts.constants import Permission

    known = {p.value for p in Permission}
    assert {*SELLER, *CALC_ONLY, *SUPPLY, *ENGINEER, *ACCOUNTANT} <= known
