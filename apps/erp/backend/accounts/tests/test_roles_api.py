"""Company roles API: create / list-scoped / assign (several roles) / guards (M1-ERP-05)."""

import pytest
from rest_framework.test import APIClient

from accounts.models import Company, CompanyMember, CompanyRole, CompanyType, CustomUser, WorkspaceRole
from accounts.services.roles import ensure_default_company_roles


def _admin_member(company, email):
    ws = WorkspaceRole.objects.get(code="OWNER")
    admin_role = CompanyRole.objects.get_or_create(
        company=company, name="Команда", defaults={"permissions": ["team.manage"]}
    )[0]
    u = CustomUser.objects.create_user(email=email, username=email, password="pw", is_active=True)
    CompanyMember.objects.create(user=u, company=company, role=ws, company_roles=[admin_role], is_active=True)
    return u


@pytest.fixture
def setup(db):
    co = Company.objects.create(name="Acme")
    co.types.add(CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier"})[0])
    admin = _admin_member(co, "admin@acme.test")
    return co, admin


def _client(user):
    c = APIClient()
    c.force_authenticate(user)
    return c


def _member(co, email, roles=()):
    user = CustomUser.objects.create_user(email=email, username=email, password="pw", is_active=True)
    return CompanyMember.objects.create(
        user=user, company=co, role=WorkspaceRole.objects.get(code="MEMBER"), company_roles=list(roles), is_active=True
    )


@pytest.mark.django_db
def test_create_role_requires_team_manage(setup):
    co, _admin = setup
    plain_role = CompanyRole.objects.create(company=co, name="Sales", permissions=["quote.send"])
    plain = _member(co, "p@acme.test", [plain_role]).user
    r = _client(plain).post("/api/v1/accounts/company-roles/", {"name": "X", "permissions": []}, format="json")
    assert r.status_code == 403
    assert r.json()["detail"] == "ROLE_NOT_PERMITTED"


@pytest.mark.django_db
def test_admin_creates_role(setup):
    co, admin = setup
    r = _client(admin).post(
        "/api/v1/accounts/company-roles/", {"name": "Логист", "permissions": ["fulfillment.manage"]}, format="json"
    )
    assert r.status_code == 201, r.content
    assert r.json()["name"] == "Логист"
    assert r.json()["code"] == ""
    assert CompanyRole.objects.get(pk=r.json()["id"]).company_id == co.id


@pytest.mark.django_db
def test_create_rejects_unknown_permission(setup):
    _co, admin = setup
    r = _client(admin).post(
        "/api/v1/accounts/company-roles/", {"name": "Bad", "permissions": ["payment.record"]}, format="json"
    )
    assert r.status_code == 400
    assert r.json()["detail"] == "UNKNOWN_PERMISSION_CODE"


@pytest.mark.django_db
def test_list_scoped_to_own_company(setup):
    co, admin = setup
    other = Company.objects.create(name="Other")
    CompanyRole.objects.create(company=other, name="Secret", permissions=[])
    ids = [x["id"] for x in _client(admin).get("/api/v1/accounts/company-roles/").json()["results"]]
    assert ids
    assert all(CompanyRole.objects.get(pk=i).company_id == co.id for i in ids)  # no cross-tenant leak


@pytest.mark.django_db
def test_cannot_delete_or_edit_system_role(setup):
    co, admin = setup
    sysrole = ensure_default_company_roles(co)["HEAD"]
    r = _client(admin).delete(f"/api/v1/accounts/company-roles/{sysrole.id}/")
    assert r.status_code == 403 and r.json()["detail"] == "SYSTEM_ROLE_IMMUTABLE"
    r = _client(admin).patch(f"/api/v1/accounts/company-roles/{sysrole.id}/", {"permissions": []}, format="json")
    assert r.status_code == 403 and r.json()["detail"] == "SYSTEM_ROLE_IMMUTABLE"


@pytest.mark.django_db
def test_assign_several_roles_to_member(setup):
    co, admin = setup
    roles = ensure_default_company_roles(co)
    member = _member(co, "t@acme.test")
    r = _client(admin).post(
        "/api/v1/accounts/company-roles/assign/",
        {"member_id": member.id, "role_ids": [roles["CALCULATION"].id, roles["FINANCE"].id]},
        format="json",
    )
    assert r.status_code == 200, r.content
    assert set(r.json()["role_ids"]) == {roles["CALCULATION"].id, roles["FINANCE"].id}
    assert set(member.company_roles.values_list("code", flat=True)) == {"CALCULATION", "FINANCE"}


@pytest.mark.django_db
def test_permission_catalog_shape(setup):
    _, admin = setup
    data = _client(admin).get("/api/v1/accounts/permissions/").json()
    assert [g["key"] for g in data["groups"]] == [
        "deals",
        "quotes",
        "contracts",
        "catalog",
        "supply",
        "fulfillment",
        "finance",
        "settings",
        "data",
    ]
    # Every permission carries code + bilingual labels (grouped checkbox contract).
    perms = [p for g in data["groups"] for p in g["permissions"]]
    assert all({"code", "label", "label_en"} <= set(p) for p in perms)
    assert "payment.record" not in {p["code"] for p in perms}


@pytest.mark.django_db
def test_cannot_drop_own_team_manage(setup):
    """Защита от тупика: снять с себя `team.manage` нельзя (иначе командой управлял бы только
    администратор из CRM)."""
    co, admin = setup
    viewer = ensure_default_company_roles(co)["VIEWER"]
    admin_member = CompanyMember.objects.get(user=admin, company=co)
    r = _client(admin).post(
        "/api/v1/accounts/company-roles/assign/",
        {"member_id": admin_member.id, "role_ids": [viewer.id]},
        format="json",
    )
    assert r.status_code == 409
    assert r.json()["detail"] == "CANNOT_DROP_OWN_TEAM_MANAGE"
    assert admin_member.company_roles.filter(name="Команда").exists()  # unchanged


@pytest.mark.django_db
def test_another_team_manager_can_reassign_an_admin(setup):
    """Пола «последнего администратора компании» у своей компании нет (администратор = is_superuser)."""
    co, admin = setup
    second = _admin_member(co, "a2@acme.test")
    viewer = ensure_default_company_roles(co)["VIEWER"]
    admin_member = CompanyMember.objects.get(user=admin, company=co)
    r = _client(second).post(
        "/api/v1/accounts/company-roles/assign/",
        {"member_id": admin_member.id, "role_ids": [viewer.id]},
        format="json",
    )
    assert r.status_code == 200, r.content
    assert list(admin_member.company_roles.values_list("code", flat=True)) == ["VIEWER"]
