"""Never-orphan invariant: a company must always keep ≥1 active admin (OWNER).

The OWNER workspace role (display label «Администратор компании») is the party
accountable for KYC/billing; removing the last one would orphan the company.
"""

import pytest

from accounts.models import Company, CompanyMember, CompanyType, CustomUser, WorkspaceRole
from accounts.services import remove_company_member, set_member_workspace_role


@pytest.fixture
def company_with_admin(db):
    CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 10})
    owner_role = WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})[0]
    manager_role = WorkspaceRole.objects.get_or_create(
        code="SALES_MANAGER", defaults={"name": "Sales Manager", "sort_order": 20}
    )[0]
    company = Company.objects.create(name="Acme LLC", inn="9911223344")
    company.types.add(CompanyType.objects.get(code="SUPPLIER"))
    admin_user = CustomUser.objects.create_user(email="admin1@acme.test", username="admin1@acme.test", password="pw")
    admin = CompanyMember.objects.create(user=admin_user, company=company, role=owner_role, is_active=True)
    return company, admin, owner_role, manager_role


@pytest.mark.django_db
def test_cannot_remove_last_admin(company_with_admin):
    _company, admin, _owner_role, _manager_role = company_with_admin
    result, error = remove_company_member(admin)
    assert result is None
    assert error == "CANNOT_REMOVE_LAST_COMPANY_ADMIN"
    assert CompanyMember.objects.filter(pk=admin.pk).exists()  # still there


@pytest.mark.django_db
def test_can_remove_admin_when_another_admin_exists(company_with_admin):
    company, admin, owner_role, _manager_role = company_with_admin
    second_user = CustomUser.objects.create_user(email="admin2@acme.test", username="admin2@acme.test", password="pw")
    CompanyMember.objects.create(user=second_user, company=company, role=owner_role, is_active=True)

    result, error = remove_company_member(admin)
    assert error is None
    assert result is True
    assert not CompanyMember.objects.filter(pk=admin.pk).exists()


@pytest.mark.django_db
def test_can_remove_non_admin_member(company_with_admin):
    company, _admin, _owner_role, manager_role = company_with_admin
    member_user = CustomUser.objects.create_user(email="mgr@acme.test", username="mgr@acme.test", password="pw")
    member = CompanyMember.objects.create(user=member_user, company=company, role=manager_role, is_active=True)

    result, error = remove_company_member(member)
    assert error is None
    assert result is True


# ─── set_member_workspace_role (delegation) ─────────────────────────────────


@pytest.mark.django_db
def test_cannot_demote_last_admin(company_with_admin):
    _company, admin, _owner_role, manager_role = company_with_admin
    result, error = set_member_workspace_role(admin, manager_role.code)
    assert result is None
    assert error == "CANNOT_DEMOTE_LAST_COMPANY_ADMIN"
    admin.refresh_from_db()
    assert admin.role.code == "OWNER"  # unchanged


@pytest.mark.django_db
def test_can_demote_admin_after_promoting_another(company_with_admin):
    company, admin, owner_role, manager_role = company_with_admin
    second_user = CustomUser.objects.create_user(email="a2@acme.test", username="a2@acme.test", password="pw")
    second = CompanyMember.objects.create(user=second_user, company=company, role=manager_role, is_active=True)

    # Promote the second member to admin, then the first can be demoted.
    _r, e1 = set_member_workspace_role(second, owner_role.code)
    assert e1 is None
    result, error = set_member_workspace_role(admin, manager_role.code)
    assert error is None
    assert result.role.code == "SALES_MANAGER"


@pytest.mark.django_db
def test_promote_member_to_admin(company_with_admin):
    company, _admin, owner_role, manager_role = company_with_admin
    user = CustomUser.objects.create_user(email="m@acme.test", username="m@acme.test", password="pw")
    member = CompanyMember.objects.create(user=user, company=company, role=manager_role, is_active=True)

    result, error = set_member_workspace_role(member, owner_role.code)
    assert error is None
    assert result.role.code == "OWNER"


@pytest.mark.django_db
def test_unknown_role_rejected(company_with_admin):
    company, _admin, _owner_role, manager_role = company_with_admin
    user = CustomUser.objects.create_user(email="x@acme.test", username="x@acme.test", password="pw")
    member = CompanyMember.objects.create(user=user, company=company, role=manager_role, is_active=True)
    result, error = set_member_workspace_role(member, "NONEXISTENT_ROLE")
    assert result is None
    assert error == "WORKSPACE_ROLE_NOT_FOUND"


@pytest.mark.django_db
def test_cannot_deactivate_sole_company_admin(company_with_admin):
    """Audit L3: deactivating the user who is the SOLE active OWNER would orphan the company."""
    from accounts.services.members import toggle_user_active

    _company, admin, _owner_role, _manager_role = company_with_admin
    requester = CustomUser.objects.create_user(email="req@x.test", username="req@x.test", password="pw")
    result, error = toggle_user_active(admin.user, requester)
    assert result is None
    assert error == "CANNOT_DEACTIVATE_SOLE_COMPANY_ADMIN"
    admin.user.refresh_from_db()
    assert admin.user.is_active is True


@pytest.mark.django_db
def test_can_deactivate_admin_when_another_exists(company_with_admin):
    from accounts.services.members import toggle_user_active

    company, admin, owner_role, _manager_role = company_with_admin
    second = CustomUser.objects.create_user(email="admin3@acme.test", username="admin3@acme.test", password="pw")
    CompanyMember.objects.create(user=second, company=company, role=owner_role, is_active=True)
    requester = CustomUser.objects.create_user(email="req2@x.test", username="req2@x.test", password="pw")
    result, error = toggle_user_active(admin.user, requester)
    assert error is None and result is not None
