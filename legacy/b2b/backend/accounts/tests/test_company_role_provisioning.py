"""U1: new tenants must get the default CompanyRoles + a mapped company_role per member.

Before the fix, only migration 0023 seeded roles — companies registered later had an empty
access matrix and members fell through to the can_sell/can_buy fallback (G4 bypassed).
"""

import pytest

from accounts.constants import COMPANY_ADMIN_ROLE_NAME, ROLE_TEMPLATES
from accounts.models import (
    CompanyMember,
    CompanyType,
    CustomUser,
    SystemRole,
    VerificationStatus,
    WorkspaceRole,
)
from accounts.services.members import invite_workspace_member
from accounts.services.profile import submit_company_profile


@pytest.fixture
def lookups(db):
    VerificationStatus.objects.get_or_create(code="PROFILE_SUBMITTED", defaults={"name": "Submitted", "sort_order": 5})
    WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 1})
    WorkspaceRole.objects.get_or_create(code="SALES_MANAGER", defaults={"name": "Sales", "sort_order": 10})
    CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Client", "sort_order": 1})
    SystemRole.objects.get_or_create(code="USER", defaults={"name": "User", "sort_order": 2})


@pytest.mark.django_db
def test_registration_seeds_default_roles_and_owner_admin(lookups):
    user = CustomUser.objects.create_user(email="founder@t.test", username="founder@t.test", password="pw")
    result, err = submit_company_profile(user, company_name="Fresh Tenant LLC")
    assert err is None

    member = CompanyMember.objects.get(user=user)
    company = member.company
    # all template roles seeded for the brand-new company
    assert set(company.roles.values_list("name", flat=True)) == set(ROLE_TEMPLATES.keys())
    # the founding OWNER holds the immutable «Администратор компании» (is_system) role
    assert member.company_role is not None
    assert member.company_role.name == COMPANY_ADMIN_ROLE_NAME
    assert member.company_role.is_system is True


@pytest.mark.django_db
def test_invite_assigns_mapped_company_role(lookups):
    founder = CustomUser.objects.create_user(email="f2@t.test", username="f2@t.test", password="pw")
    submit_company_profile(founder, company_name="Inviter LLC")
    company = CompanyMember.objects.get(user=founder).company

    invited, err = invite_workspace_member(company, "sales@t.test", "SALES_MANAGER")
    assert err is None
    member = CompanyMember.objects.get(user=invited)
    # SALES_MANAGER → «Менеджер по продажам» (not None, not the can_sell/can_buy fallback)
    assert member.company_role is not None
    assert member.company_role.name == "Менеджер по продажам"
