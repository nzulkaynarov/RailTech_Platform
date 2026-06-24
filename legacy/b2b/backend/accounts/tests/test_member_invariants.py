"""Never-orphan invariant: a company must always keep ≥1 active admin (OWNER).

The OWNER workspace role (display label «Администратор компании») is the party
accountable for KYC/billing; removing the last one would orphan the company.
"""

import pytest

from accounts.models import Company, CompanyMember, CompanyType, CustomUser, WorkspaceRole
from accounts.services import remove_company_member


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
