"""Тесты для Wave J7 (Статус отношений и архив документов) и Wave J2-audit (Журнал безопасности компании)."""

from __future__ import annotations

import datetime

import pytest
from parties.models import Company, CompanyRelationship, CompanyType, Contact, RelationshipRole, RelationshipStatus
from portal.tests.conftest import PortalAPIClient, make_portal_session

pytestmark = pytest.mark.django_db

PREFIX = "/api/portal/v1"


@pytest.fixture
def j7_setup():
    client_type, _ = CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Клиент"})
    company = Company.objects.create(name="J7 Trans LLC", inn="770022334")
    company.types.add(client_type)

    admin_contact = Contact.objects.create(
        company=company,
        name="Admin Contact",
        email="admin@j7.test",
        can_act=True,
        is_admin=True,
    )
    admin_session = make_portal_session(admin_contact, company, "magic_link")
    admin_client = PortalAPIClient()
    admin_client.cookies["portal_session"] = admin_session.raw_token
    admin_client.credentials(HTTP_X_PORTAL_SESSION=admin_session.raw_token)

    regular_contact = Contact.objects.create(
        company=company,
        name="Regular Contact",
        email="regular@j7.test",
        can_act=True,
        is_admin=False,
    )
    regular_session = make_portal_session(regular_contact, company, "magic_link")
    regular_client = PortalAPIClient()
    regular_client.cookies["portal_session"] = regular_session.raw_token
    regular_client.credentials(HTTP_X_PORTAL_SESSION=regular_session.raw_token)

    return {
        "company": company,
        "admin_contact": admin_contact,
        "admin_session": admin_session,
        "admin_client": admin_client,
        "regular_contact": regular_contact,
        "regular_session": regular_session,
        "regular_client": regular_client,
    }


def test_company_relationship_status_projection(j7_setup):
    admin_client = j7_setup["admin_client"]
    company = j7_setup["company"]

    # 1. По умолчанию для активного клиента статус "active"
    res = admin_client.get(f"{PREFIX}/company")
    assert res.status_code == 200
    data = res.json()
    assert data["relationship_status"] == "active"
    assert len(data["relationships"]) >= 1
    assert data["relationships"][0]["role"] == "client"
    assert data["relationships"][0]["status"] == "active"

    # Также проверяем через /me
    me_res = admin_client.get(f"{PREFIX}/me")
    assert me_res.status_code == 200
    me_data = me_res.json()
    assert me_data["company"]["relationship_status"] == "active"

    # 2. Добавляем явное отношение с контрактом в статусе suspended
    rel = CompanyRelationship.objects.create(
        company=company,
        role=RelationshipRole.CLIENT,
        status=RelationshipStatus.SUSPENDED,
        contract_number="CTR-J7-2026",
        contract_date=datetime.date(2026, 1, 15),
    )

    res2 = admin_client.get(f"{PREFIX}/company")
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2["relationship_status"] == "suspended"
    assert any(
        r["role"] == "client" and r["status"] == "suspended" and r["contract_number"] == "CTR-J7-2026"
        for r in data2["relationships"]
    )

    # 3. Переводим отношение в terminated
    rel.status = RelationshipStatus.TERMINATED
    rel.save()

    res3 = admin_client.get(f"{PREFIX}/company")
    assert res3.status_code == 200
    assert res3.json()["relationship_status"] == "terminated"


def test_company_security_log_permissions_and_records(j7_setup):
    admin_client = j7_setup["admin_client"]
    regular_client = j7_setup["regular_client"]
    company = j7_setup["company"]
    admin_contact = j7_setup["admin_contact"]

    # 1. Обычный сотрудник (не админ) получает 403 ADMIN_REQUIRED
    res_forbidden = regular_client.get(f"{PREFIX}/company/security-log")
    assert res_forbidden.status_code == 403

    # 2. Администратор получает 200 OK
    res_ok = admin_client.get(f"{PREFIX}/company/security-log")
    assert res_ok.status_code == 200
    items = res_ok.json()["items"]
    assert isinstance(items, list)

    # 3. Проверяем создание события смены прав коллеги
    colleague = Contact.objects.create(
        company=company,
        name="Junior Colleague",
        email="junior@j7.test",
        can_act=False,
        is_admin=False,
    )
    patch_res = admin_client.patch(
        f"{PREFIX}/team/{colleague.pk}",
        {"can_act": True, "is_admin": False},
        format="json",
    )
    assert patch_res.status_code == 200

    log_res = admin_client.get(f"{PREFIX}/company/security-log")
    assert log_res.status_code == 200
    log_items = log_res.json()["items"]
    role_change_event = next((e for e in log_items if e["event_type"] == "role_change"), None)
    assert role_change_event is not None
    assert role_change_event["actor_name"] == admin_contact.name
    assert role_change_event["target_name"] == colleague.name
    assert "can_act=True" in role_change_event["details"]

    # 4. Проверяем событие отключения коллеги
    deact_res = admin_client.post(f"{PREFIX}/team/{colleague.pk}/deactivate")
    assert deact_res.status_code == 200

    log_res2 = admin_client.get(f"{PREFIX}/company/security-log")
    log_items2 = log_res2.json()["items"]
    deact_event = next((e for e in log_items2 if e["event_type"] == "member_deactivated"), None)
    assert deact_event is not None
    assert deact_event["target_name"] == colleague.name

    # 5. Проверяем событие смены банковских реквизитов
    bank_res = admin_client.put(
        f"{PREFIX}/company",
        {"bank_details": "IBAN: UZ12345678901234567890\nBank: NBU"},
        format="json",
    )
    assert bank_res.status_code == 200

    log_res3 = admin_client.get(f"{PREFIX}/company/security-log")
    log_items3 = log_res3.json()["items"]
    bank_event = next((e for e in log_items3 if e["event_type"] == "bank_details_changed"), None)
    assert bank_event is not None
    assert bank_event["actor_name"] == admin_contact.name
