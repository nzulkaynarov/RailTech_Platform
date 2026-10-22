"""Реквизиты клиента ведёт CRM (B3, ORCHESTRATOR §3 п. 16): `PUT /company` отвергает правку названия и ИНН компании,
связанной с клиентом CRM, кодом `REQUISITES_MANAGED_BY_CRM` (422); остальное профиль правит как раньше."""

import pytest
from integration.models import CrmClientMapping

pytestmark = pytest.mark.django_db


def test_portal_rejects_a_change_of_name_or_inn_of_a_crm_company(portal_client, client_company):
    CrmClientMapping.objects.create(company=client_company, crm_client_id=4242)
    old = (client_company.name, client_company.inn)
    for body in ({"name": "Новое имя"}, {"inn": "123456789"}):
        response = portal_client.put("/api/portal/v1/company", body, format="json")
        assert response.status_code == 422
        assert response.json() == {"detail": "REQUISITES_MANAGED_BY_CRM"}
    client_company.refresh_from_db()
    assert (client_company.name, client_company.inn) == old


def test_portal_still_updates_the_rest_of_the_profile_of_a_crm_company(portal_client, client_company):
    CrmClientMapping.objects.create(company=client_company, crm_client_id=4242)
    response = portal_client.put(
        "/api/portal/v1/company",
        {"name": client_company.name, "bank_details": "р/с 2020", "language": "uz"},
        format="json",
    )
    assert response.status_code == 200
    assert response.json()["bank_details"] == "р/с 2020"


def test_portal_edits_the_name_of_a_company_without_crm(portal_client, client_company):
    response = portal_client.put("/api/portal/v1/company", {"name": "Новое имя"}, format="json")
    assert response.status_code == 200 and response.json()["name"] == "Новое имя"
