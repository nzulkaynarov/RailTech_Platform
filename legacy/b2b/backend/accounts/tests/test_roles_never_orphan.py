"""Never-orphan gap on assign_role_to_member (review finding, 2026-07-09).

The guard used to check only is_system CompanyRole holders, so a SOLE un-migrated legacy OWNER
(WorkspaceRole OWNER, company_role IS NULL — admin via the OWNER permission fallback) could
reassign themselves to a permission-less role and orphan the company. The guard now uses the
UNIFIED admin floor (members._admin_floor_q: is_system OR legacy NULL-OWNER)."""

import pytest

from accounts.models import Company, CompanyMember, CompanyRole, CompanyType, CustomUser, WorkspaceRole
from accounts.services.roles import assign_role_to_member


@pytest.fixture
def company(db):
    CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 10})
    WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})
    WorkspaceRole.objects.get_or_create(code="MEMBER", defaults={"name": "Member", "sort_order": 30})
    co = Company.objects.create(name="Orphan Co", inn="9900110022")
    co.types.add(CompanyType.objects.get(code="SUPPLIER"))
    plain = CompanyRole.objects.create(company=co, name="Наблюдатель", permissions=[])
    admin_role = CompanyRole.objects.create(company=co, name="Администратор компании", is_system=True)
    return co, plain, admin_role


def _owner(co, email):
    user = CustomUser.objects.create_user(email=email, username=email, password="pw", is_active=True)
    member = CompanyMember.objects.create(
        user=user, company=co, role=WorkspaceRole.objects.get(code="OWNER"), company_role=None, is_active=True
    )
    return user, member


@pytest.mark.django_db
def test_sole_legacy_owner_cannot_self_demote_to_non_system_role(company):
    """The exact gap: a sole legacy OWNER (company_role IS NULL) reassigned to a permission-less
    role would orphan the company. Must be blocked by the unified floor."""
    co, plain, _admin_role = company
    user, member = _owner(co, "solo@orphan.test")
    result, error = assign_role_to_member(user, member.pk, plain.pk)
    assert result is None
    assert error == "CANNOT_DEMOTE_LAST_COMPANY_ADMIN"
    member.refresh_from_db()
    assert member.company_role_id is None  # unchanged


@pytest.mark.django_db
def test_legacy_owner_can_be_reassigned_when_another_admin_exists(company):
    co, plain, admin_role = company
    user, member = _owner(co, "owner@orphan.test")
    # A second admin via an is_system CompanyRole → the floor is not breached.
    second = CustomUser.objects.create_user(email="admin2@orphan.test", username="admin2@orphan.test", password="pw")
    CompanyMember.objects.create(user=second, company=co, role=WorkspaceRole.objects.get(code="MEMBER"), company_role=admin_role, is_active=True)

    result, error = assign_role_to_member(user, member.pk, plain.pk)
    assert error is None
    assert result is not None
    member.refresh_from_db()
    assert member.company_role_id == plain.pk


@pytest.mark.django_db
def test_sole_is_system_admin_still_cannot_self_demote(company):
    """Regression: the original is_system sole-admin protection is preserved."""
    co, plain, admin_role = company
    user = CustomUser.objects.create_user(email="sys@orphan.test", username="sys@orphan.test", password="pw")
    member = CompanyMember.objects.create(user=user, company=co, role=WorkspaceRole.objects.get(code="MEMBER"), company_role=admin_role, is_active=True)
    result, error = assign_role_to_member(user, member.pk, plain.pk)
    assert result is None
    assert error == "CANNOT_DEMOTE_LAST_COMPANY_ADMIN"
