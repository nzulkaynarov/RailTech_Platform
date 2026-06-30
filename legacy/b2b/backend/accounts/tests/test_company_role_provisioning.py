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


@pytest.mark.django_db
def test_company_config_gate_allows_delegated_admin_not_regular_member(lookups):
    """ADR-0005 U2: company-config gate (is_company_owner) keys on settings.edit, so a delegated
    «Администратор компании» (NOT WorkspaceRole OWNER) passes and a regular member does not."""
    from accounts.models import CompanyRole
    from accounts.services.document_profile import is_company_owner

    founder = CustomUser.objects.create_user(email="own@t.test", username="own@t.test", password="pw")
    submit_company_profile(founder, company_name="Deleg LLC")
    company = CompanyMember.objects.get(user=founder).company
    member_ws = WorkspaceRole.objects.get_or_create(code="MEMBER", defaults={"name": "Member", "sort_order": 50})[0]

    # delegated admin: the is_system «Администратор компании» role on a non-OWNER member
    admin_role = CompanyRole.objects.get(company=company, name=COMPANY_ADMIN_ROLE_NAME)
    delegate = CustomUser.objects.create_user(email="deleg@t.test", username="deleg@t.test", password="pw")
    CompanyMember.objects.create(user=delegate, company=company, role=member_ws, company_role=admin_role, is_active=True)
    assert is_company_owner(delegate, company) is True

    # regular member: «Наблюдатель» (no settings.edit) must NOT manage company config
    viewer_role = CompanyRole.objects.get(company=company, name="Наблюдатель")
    viewer = CustomUser.objects.create_user(email="view@t.test", username="view@t.test", password="pw")
    CompanyMember.objects.create(user=viewer, company=company, role=member_ws, company_role=viewer_role, is_active=True)
    assert is_company_owner(viewer, company) is False


@pytest.mark.django_db
def test_me_capabilities_object(lookups):
    """ADR-0005 Phase B: /me exposes a consolidated capabilities object the unified nav reads."""
    from accounts.constants import ALL_PERMISSIONS
    from accounts.serializers import MeSerializer

    founder = CustomUser.objects.create_user(email="caps@t.test", username="caps@t.test", password="pw")
    submit_company_profile(founder, company_name="Caps LLC")
    caps = MeSerializer(founder).data["capabilities"]

    assert caps["can_buy"] is True  # CLIENT company, default can_buy
    # OWNER holds the is_system admin role → ALL_PERMISSIONS (mirrors CompanyRole.has_perm)
    assert set(caps["permissions"]) == set(ALL_PERMISSIONS)
    assert caps["is_platform_admin"] is False
    assert "kyc_level" in caps and "subscription_active" in caps
