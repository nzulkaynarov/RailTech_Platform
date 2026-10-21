"""FIX-55 / D-15: роли «CRM Sync: …» ведёт провижининг из CRM — в «Команде» их назначить нельзя.

Список ролей по умолчанию их не отдаёт (`?include_managed=true` — отдаёт с признаком `managed_by_crm`);
`assign` не добавляет чужую управляемую роль и не снимает собственную сотрудника (выбор в интерфейсе её не
содержит); править и удалять такую роль нельзя.
"""

import pytest

from accounts.models import CompanyRole
from accounts.tests.test_roles_api import _client, _member, setup  # noqa: F401

ROLES = "/api/v1/accounts/company-roles/"


@pytest.fixture
def managed(setup):  # noqa: F811
    co, admin = setup
    own = CompanyRole.objects.create(
        company=co, name="CRM Sync: staff@acme.test", permissions=["quote.build"], managed_by_crm=True
    )
    other = CompanyRole.objects.create(
        company=co, name="CRM Sync: other@acme.test", permissions=["quote.send"], managed_by_crm=True
    )
    manual = CompanyRole.objects.create(company=co, name="Склад", permissions=["supply.manage"])
    staff = _member(co, "staff@acme.test", [own])
    return {"co": co, "admin": admin, "own": own, "other": other, "manual": manual, "staff": staff}


@pytest.mark.django_db
def test_list_hides_managed_roles_by_default(managed):
    names = [row["name"] for row in _client(managed["admin"]).get(ROLES).json()["results"]]
    assert "Склад" in names
    assert not [name for name in names if name.startswith("CRM Sync")]


@pytest.mark.django_db
def test_list_can_include_managed_roles_with_flag(managed):
    rows = _client(managed["admin"]).get(ROLES, {"include_managed": "true"}).json()["results"]
    flags = {row["name"]: row["managed_by_crm"] for row in rows}
    assert flags["CRM Sync: other@acme.test"] is True
    assert flags["Склад"] is False


@pytest.mark.django_db
def test_assign_foreign_managed_role_is_refused(managed):
    response = _client(managed["admin"]).post(
        ROLES + "assign/",
        {"member_id": managed["staff"].id, "role_ids": [managed["manual"].id, managed["other"].id]},
        format="json",
    )
    assert response.status_code == 403, response.content
    assert response.json()["detail"] == "ROLE_MANAGED_BY_CRM"
    assert set(managed["staff"].company_roles.values_list("id", flat=True)) == {managed["own"].id}


@pytest.mark.django_db
def test_assign_keeps_members_own_managed_role_when_picker_omits_it(managed):
    response = _client(managed["admin"]).post(
        ROLES + "assign/",
        {"member_id": managed["staff"].id, "role_ids": [managed["manual"].id]},
        format="json",
    )
    assert response.status_code == 200, response.content
    assert set(response.json()["role_ids"]) == {managed["manual"].id, managed["own"].id}


@pytest.mark.django_db
def test_assign_with_members_own_managed_role_is_allowed(managed):
    response = _client(managed["admin"]).post(
        ROLES + "assign/",
        {"member_id": managed["staff"].id, "role_ids": [managed["manual"].id, managed["own"].id]},
        format="json",
    )
    assert response.status_code == 200, response.content


@pytest.mark.django_db
def test_managed_role_cannot_be_edited_or_deleted(managed):
    client = _client(managed["admin"])
    response = client.patch(f"{ROLES}{managed['own'].id}/", {"permissions": []}, format="json")
    assert response.status_code == 403 and response.json()["detail"] == "ROLE_MANAGED_BY_CRM"
    response = client.delete(f"{ROLES}{managed['other'].id}/")
    assert response.status_code == 403 and response.json()["detail"] == "ROLE_MANAGED_BY_CRM"


@pytest.mark.django_db
def test_hand_made_role_cannot_take_the_reserved_name(managed):
    response = _client(managed["admin"]).post(
        ROLES, {"name": "CRM Sync: fake@acme.test", "permissions": []}, format="json"
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "ROLE_NAME_RESERVED"
