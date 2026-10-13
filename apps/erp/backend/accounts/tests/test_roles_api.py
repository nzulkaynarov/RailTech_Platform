"""Company roles API: create/list-scoped/assign/guards (RBAC phase 2)."""

import pytest
from rest_framework.test import APIClient

from accounts.models import Company, CompanyMember, CompanyRole, CustomUser, WorkspaceRole


def _admin_member(company, email):
    ws = WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})[0]
    admin_role = CompanyRole.objects.create(company=company, name="Админ", permissions=["team.manage"], is_system=True)
    u = CustomUser.objects.create_user(email=email, username=email, password="pw", is_active=True)
    CompanyMember.objects.create(user=u, company=company, role=ws, company_role=admin_role, is_active=True)
    return u


@pytest.fixture
def setup(db):
    co = Company.objects.create(name="Acme")
    admin = _admin_member(co, "admin@acme.test")
    return co, admin


def _client(user):
    c = APIClient()
    c.force_authenticate(user)
    return c


@pytest.mark.django_db
def test_create_role_requires_team_manage(setup):
    co, admin = setup
    # plain member without team.manage
    plain_role = CompanyRole.objects.create(company=co, name="Sales", permissions=["quote.send"])
    plain = CustomUser.objects.create_user(email="p@acme.test", username="p@acme.test", password="pw", is_active=True)
    ws = WorkspaceRole.objects.get(code="OWNER")
    CompanyMember.objects.create(
        user=plain, company=co, role=ws, company_role=plain_role, is_active=True, can_sell=False, can_buy=False
    )
    r = _client(plain).post("/api/v1/accounts/company-roles/", {"name": "X", "permissions": []}, format="json")
    assert r.status_code == 403


@pytest.mark.django_db
def test_admin_creates_role(setup):
    co, admin = setup
    r = _client(admin).post(
        "/api/v1/accounts/company-roles/", {"name": "Логист", "permissions": ["catalog.manage"]}, format="json"
    )
    assert r.status_code == 201, r.content
    assert r.json()["name"] == "Логист"


@pytest.mark.django_db
def test_create_rejects_unknown_permission(setup):
    co, admin = setup
    r = _client(admin).post(
        "/api/v1/accounts/company-roles/", {"name": "Bad", "permissions": ["not.a.perm"]}, format="json"
    )
    assert r.status_code == 400


@pytest.mark.django_db
def test_list_scoped_to_own_company(setup):
    co, admin = setup
    other = Company.objects.create(name="Other")
    CompanyRole.objects.create(company=other, name="Secret", permissions=[])
    ids = [x["id"] for x in _client(admin).get("/api/v1/accounts/company-roles/").json()["results"]]
    assert all(CompanyRole.objects.get(pk=i).company_id == co.id for i in ids)  # no cross-tenant leak


@pytest.mark.django_db
def test_cannot_delete_system_role(setup):
    co, admin = setup
    sysrole = CompanyRole.objects.get(company=co, is_system=True)
    assert _client(admin).delete(f"/api/v1/accounts/company-roles/{sysrole.id}/").status_code == 403


@pytest.mark.django_db
def test_assign_role_to_member(setup):
    co, admin = setup
    sales = CompanyRole.objects.create(company=co, name="Sales", permissions=["quote.send"])
    # Assign to a NON-admin member (reassigning the sole is_system admin is blocked by the
    # never-orphan invariant — covered by test_cannot_strip_last_company_admin).
    ws = WorkspaceRole.objects.get(code="OWNER")
    target_user = CustomUser.objects.create_user(
        email="t@acme.test", username="t@acme.test", password="pw", is_active=True
    )
    member = CompanyMember.objects.create(user=target_user, company=co, role=ws, is_active=True)
    r = _client(admin).post(
        "/api/v1/accounts/company-roles/assign/", {"member_id": member.id, "role_id": sales.id}, format="json"
    )
    assert r.status_code == 200
    member.refresh_from_db()
    assert member.company_role_id == sales.id


@pytest.mark.django_db
def test_permission_catalog_shape(setup):
    _, admin = setup
    data = _client(admin).get("/api/v1/accounts/permissions/").json()
    assert "groups" in data and len(data["groups"]) >= 4
    assert all("permissions" in g for g in data["groups"])
    # Every permission carries code + bilingual labels (grouped checkbox contract).
    perms = [p for g in data["groups"] for p in g["permissions"]]
    assert all({"code", "label", "label_en"} <= set(p) for p in perms)


@pytest.mark.django_db
def test_cannot_strip_last_company_admin(setup):
    """Never-orphan (ADR-0004): reassigning the sole is_system holder to a non-system role
    must be refused — transfer admin first."""
    co, admin = setup
    viewer = CompanyRole.objects.create(company=co, name="Наблюдатель", permissions=[])
    admin_member = CompanyMember.objects.get(user=admin, company=co)
    r = _client(admin).post(
        "/api/v1/accounts/company-roles/assign/",
        {"member_id": admin_member.id, "role_id": viewer.id},
        format="json",
    )
    assert r.status_code == 409
    assert r.json()["detail"] == "CANNOT_DEMOTE_LAST_COMPANY_ADMIN"
    admin_member.refresh_from_db()
    assert admin_member.company_role.is_system is True  # unchanged


@pytest.mark.django_db
def test_can_strip_admin_when_another_admin_exists(setup):
    """The same reassignment is allowed once a second is_system admin exists."""
    co, admin = setup
    # second admin holding the system role
    sys_role = CompanyRole.objects.get(company=co, is_system=True)
    ws = WorkspaceRole.objects.get(code="OWNER")
    u2 = CustomUser.objects.create_user(email="a2@acme.test", username="a2@acme.test", password="pw", is_active=True)
    CompanyMember.objects.create(user=u2, company=co, role=ws, company_role=sys_role, is_active=True)

    viewer = CompanyRole.objects.create(company=co, name="Наблюдатель", permissions=[])
    admin_member = CompanyMember.objects.get(user=admin, company=co)
    r = _client(admin).post(
        "/api/v1/accounts/company-roles/assign/",
        {"member_id": admin_member.id, "role_id": viewer.id},
        format="json",
    )
    assert r.status_code == 200, r.content
    admin_member.refresh_from_db()
    assert admin_member.company_role_id == viewer.id
