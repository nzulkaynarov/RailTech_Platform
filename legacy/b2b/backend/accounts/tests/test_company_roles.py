"""Company Role+Permission-set model + member_has_permission (RBAC matrix, phase 1)."""

import pytest

from accounts.models import Company, CompanyMember, CompanyRole, CustomUser, WorkspaceRole
from accounts.services import member_has_permission


@pytest.fixture
def company(db):
    return Company.objects.create(name="Acme")


def _member(company, email, *, role=None, can_sell=True, can_buy=True, wsrole_code="MEMBER"):
    ws = WorkspaceRole.objects.get_or_create(code=wsrole_code, defaults={"name": wsrole_code, "sort_order": 10})[0]
    user = CustomUser.objects.create_user(email=email, username=email, password="pw", is_active=True)
    return CompanyMember.objects.create(
        user=user, company=company, role=ws, company_role=role,
        is_active=True, can_sell=can_sell, can_buy=can_buy,
    )


@pytest.mark.django_db
def test_company_role_has_perm(company):
    role = CompanyRole.objects.create(company=company, name="Sales", permissions=["quote.send", "quote.build"])
    assert role.has_perm("quote.send") is True
    assert role.has_perm("payment.record") is False


@pytest.mark.django_db
def test_system_role_has_all(company):
    role = CompanyRole.objects.create(company=company, name="Admin", permissions=[], is_system=True)
    assert role.has_perm("anything.at.all") is True


@pytest.mark.django_db
def test_member_permission_from_company_role(company):
    role = CompanyRole.objects.create(company=company, name="Sales", permissions=["quote.send"])
    m = _member(company, "s@a.test", role=role)
    assert member_has_permission(m.user, company.id, "quote.send") is True
    assert member_has_permission(m.user, company.id, "payment.record") is False


@pytest.mark.django_db
def test_legacy_fallback_when_no_company_role(company):
    # No company_role → derive from can_sell/can_buy.
    seller = _member(company, "sell@a.test", role=None, can_sell=True, can_buy=False)
    assert member_has_permission(seller.user, company.id, "quote.send") is True       # sell perm
    assert member_has_permission(seller.user, company.id, "contract.sign") is False   # buy perm
    assert member_has_permission(seller.user, company.id, "team.manage") is False     # admin perm


@pytest.mark.django_db
def test_legacy_owner_has_all(company):
    owner = _member(company, "own@a.test", role=None, wsrole_code="OWNER")
    assert member_has_permission(owner.user, company.id, "team.manage") is True
    assert member_has_permission(owner.user, company.id, "settings.edit") is True


@pytest.mark.django_db
def test_non_member_denied(company):
    outsider = CustomUser.objects.create_user(email="out@x.test", username="out@x.test", password="pw", is_active=True)
    assert member_has_permission(outsider, company.id, "quote.send") is False


@pytest.mark.django_db
def test_role_name_unique_per_company(company):
    CompanyRole.objects.create(company=company, name="Dup", permissions=[])
    from django.db import IntegrityError

    with pytest.raises(IntegrityError):
        CompanyRole.objects.create(company=company, name="Dup", permissions=[])
