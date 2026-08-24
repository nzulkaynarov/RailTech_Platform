"""Lock-down tests for the Platform Operator sub-role access matrix (ADR-0004 G1).

This is the SECURITY CONTRACT for the operator plane: which platform-staff actions
each seeded operator sub-role (SUPPORT / KYC_OFFICER / BILLING_OPERATOR / MODERATOR /
SUPER_OPERATOR) may take. Three layers are pinned:

  * Group A — `operator_has_permission` unit truth table (no HTTP).
  * Group B — the DRF `OperatorScoped` gate at the endpoint layer (status codes).
  * Group C — the operator-role management service (Rule 8: create/update/delete/assign +
    the never-orphan floor on `operators.manage`).

NB: the suite runs with `--nomigrations` (pyproject addopts), so the data-migration
`accounts/0027_seed_operator_roles` does NOT run. The `operator_roles` fixture seeds the
five presets from the canonical `accounts.constants.OPERATOR_ROLE_TEMPLATES` — the same
source of truth migration 0027 inlines — so the matrix under test is identical to prod.
"""

import pytest
from rest_framework.test import APIClient

from accounts import services
from accounts.constants import ALL_OPERATOR_PERMISSIONS, OPERATOR_ROLE_TEMPLATES, OperatorPermission, OperatorRoleCode
from accounts.models import CompanyMember, CustomUser, OperatorRole, SupplierSubscription, VerificationStatus
from accounts.services.permissions import operator_has_permission

pytestmark = pytest.mark.django_db


# ──────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────


@pytest.fixture
def operator_roles(db):
    """The five seeded operator presets, keyed by code.

    Mirrors migration 0027 by get_or_create-ing from OPERATOR_ROLE_TEMPLATES (the
    constants source of truth) because --nomigrations skips the seed migration.
    """
    roles = {}
    for code, template in OPERATOR_ROLE_TEMPLATES.items():
        role, _ = OperatorRole.objects.get_or_create(
            code=code,
            defaults={
                "name": template["name"],
                "permissions": list(template["permissions"]),
                "is_system": template["is_system"],
                "description": template.get("description", ""),
            },
        )
        roles[code] = role
    return roles


@pytest.fixture
def make_operator(db, system_role_factory, operator_roles):
    """Factory → a Platform Operator: SystemRole.ADMIN, NO membership, given preset.

    Pass an OperatorRoleCode value to attach that preset, or None for "no operator_role"
    (backward-compatible full access == the legacy single ADMIN).
    """
    admin_role = system_role_factory(code="ADMIN", name="Администратор платформы")
    counter = {"n": 0}

    def _make(preset_code):
        counter["n"] += 1
        suffix = counter["n"]
        user = CustomUser.objects.create_user(
            email=f"operator{suffix}@platform.test",
            username=f"operator{suffix}",
            password="oppass123",
            is_active=True,
        )
        user.role = admin_role
        user.operator_role = operator_roles[preset_code] if preset_code else None
        user.save(update_fields=["role", "operator_role"])
        return user

    return _make


@pytest.fixture
def normal_user(db, system_role_factory, workspace_role_factory, company_factory):
    """A non-platform user (SystemRole.USER) with an active seller membership — the
    'normal CLIENT/seller user' that must hold ZERO operator capabilities."""
    user_role = system_role_factory(code="USER", name="Пользователь")
    user = CustomUser.objects.create_user(
        email="seller-member@tenant.test",
        username="seller-member",
        password="userpass123",
        is_active=True,
    )
    user.role = user_role
    user.save(update_fields=["role"])
    company = company_factory(name="Tenant Co", inn="7777777777", email="tenant@tenant.test")
    CompanyMember.objects.create(
        user=user,
        company=company,
        role=workspace_role_factory(code="SALES_MANAGER", name="Менеджер по продажам"),
        is_active=True,
        is_primary=True,
        can_sell=True,
    )
    return user


@pytest.fixture
def superuser(db):
    """is_superuser=True but NOT a platform-admin-role operator (DBA emergency bypass)."""
    return CustomUser.objects.create_superuser(email="root@platform.test", username="root", password="rootpass123")


@pytest.fixture
def verification_statuses(db):
    """KYC levels so a verify-kyc POST has a real target status (not just a 400 path)."""
    for code, name, rank in [
        ("L1_UNVERIFIED", "L1", 10),
        ("PROFILE_SUBMITTED", "Submitted", 20),
        ("L2_VERIFIED", "L2", 30),
        ("L3_CONTRACTED", "L3", 40),
    ]:
        VerificationStatus.objects.get_or_create(code=code, defaults={"name": name, "sort_order": rank})


def _auth_client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


# ══════════════════════════════════════════════════════════════════════════
# GROUP A — operator_has_permission truth table (no HTTP)
# ══════════════════════════════════════════════════════════════════════════


def test_super_operator_has_every_capability(make_operator):
    operator = make_operator(OperatorRoleCode.SUPER_OPERATOR.value)
    # 12 → 14: добавлены `leads.view` и `leads.route` вместе с механикой «очередь лидов →
    # назначение компании → приём» (Salesforce Lead Queue). Число здесь — не украшение: оно
    # ловит право, добавленное в enum и забытое в пресетах ролей.
    assert len(ALL_OPERATOR_PERMISSIONS) == 14
    for perm in ALL_OPERATOR_PERMISSIONS:
        assert operator_has_permission(operator, perm) is True, perm


def test_support_capability_set(make_operator):
    operator = make_operator(OperatorRoleCode.SUPPORT.value)
    for granted in (
        OperatorPermission.USERS_VIEW.value,
        OperatorPermission.COMPANIES_VIEW.value,
        OperatorPermission.KYC_VIEW.value,
        OperatorPermission.BILLING_VIEW.value,
    ):
        assert operator_has_permission(operator, granted) is True, granted
    for denied in (
        OperatorPermission.KYC_VERIFY.value,
        OperatorPermission.BILLING_MANAGE.value,
        OperatorPermission.MODERATION_FORCE_OVERRIDE.value,
        OperatorPermission.OPERATORS_MANAGE.value,
        OperatorPermission.USERS_MANAGE.value,
    ):
        assert operator_has_permission(operator, denied) is False, denied


def test_kyc_officer_capability_set(make_operator):
    operator = make_operator(OperatorRoleCode.KYC_OFFICER.value)
    assert operator_has_permission(operator, OperatorPermission.KYC_VERIFY.value) is True
    assert operator_has_permission(operator, OperatorPermission.BILLING_MANAGE.value) is False
    assert operator_has_permission(operator, OperatorPermission.MODERATION_FORCE_OVERRIDE.value) is False


def test_billing_operator_capability_set(make_operator):
    operator = make_operator(OperatorRoleCode.BILLING_OPERATOR.value)
    assert operator_has_permission(operator, OperatorPermission.BILLING_MANAGE.value) is True
    assert operator_has_permission(operator, OperatorPermission.KYC_VERIFY.value) is False
    assert operator_has_permission(operator, OperatorPermission.MODERATION_FORCE_OVERRIDE.value) is False


def test_moderator_capability_set(make_operator):
    operator = make_operator(OperatorRoleCode.MODERATOR.value)
    assert operator_has_permission(operator, OperatorPermission.MODERATION_FORCE_OVERRIDE.value) is True
    assert operator_has_permission(operator, OperatorPermission.MODERATION_ROLE_APPLICATIONS.value) is True
    assert operator_has_permission(operator, OperatorPermission.KYC_VERIFY.value) is False
    assert operator_has_permission(operator, OperatorPermission.BILLING_MANAGE.value) is False


def test_operator_with_no_role_is_backward_compatible_full_access(make_operator):
    operator = make_operator(None)
    assert operator.operator_role is None
    for perm in ALL_OPERATOR_PERMISSIONS:
        assert operator_has_permission(operator, perm) is True, perm


def test_superuser_has_every_capability(superuser):
    for perm in ALL_OPERATOR_PERMISSIONS:
        assert operator_has_permission(superuser, perm) is True, perm


def test_normal_tenant_user_has_no_capability(normal_user):
    for perm in ALL_OPERATOR_PERMISSIONS:
        assert operator_has_permission(normal_user, perm) is False, perm


# ══════════════════════════════════════════════════════════════════════════
# GROUP B — DRF OperatorScoped gate (status codes). We assert AUTHZ only:
# != 403 means "allowed at the permission layer" (the action may still 400/404).
# ══════════════════════════════════════════════════════════════════════════


@pytest.fixture
def company(company_factory, verification_statuses):
    return company_factory(name="KYC Target", inn="5555500001", email="kyc@target.test")


@pytest.fixture
def subscription(company_factory):
    target = company_factory(name="Sub Co", inn="5555500002", email="sub@co.test")
    return SupplierSubscription.objects.create(company=target, plan="BASIC", status="TRIAL")


@pytest.fixture
def quote(db, company_factory):
    from crm.models import Deal, DealStage, Quote, QuoteStatus

    stage = DealStage.objects.get_or_create(code="DRAFT", defaults={"name": "Draft", "sort_order": 0})[0]
    draft_status = QuoteStatus.objects.get_or_create(code="DRAFT", defaults={"name": "Draft"})[0]
    buyer = company_factory(name="Buyer Co", inn="5555500003", email="buyer@co.test")
    deal = Deal.objects.create(company=buyer, stage=stage)
    return Quote.objects.create(deal=deal, version=1, status=draft_status)


def _verify_kyc_url(company):
    from django.urls import reverse

    return reverse("company-verify-kyc", kwargs={"pk": company.pk})


def _activate_sub_url(subscription):
    from django.urls import reverse

    return reverse("subscription-activate", kwargs={"pk": subscription.pk})


def _force_approve_url(quote):
    from django.urls import reverse

    return reverse("quote-force-approve", kwargs={"pk": quote.pk})


def _users_list_url():
    from django.urls import reverse

    return reverse("customuser-list")


def test_http_kyc_officer_can_verify_but_not_bill_or_override(make_operator, company, subscription, quote):
    client = _auth_client(make_operator(OperatorRoleCode.KYC_OFFICER.value))
    assert client.post(_verify_kyc_url(company), {"status_code": "L2_VERIFIED"}, format="json").status_code != 403
    assert client.post(_activate_sub_url(subscription), {}, format="json").status_code == 403
    assert client.post(_force_approve_url(quote), {"reason": "x"}, format="json").status_code == 403


def test_http_billing_operator_can_activate_but_not_verify(make_operator, company, subscription):
    client = _auth_client(make_operator(OperatorRoleCode.BILLING_OPERATOR.value))
    assert client.post(_activate_sub_url(subscription), {}, format="json").status_code != 403
    assert client.post(_verify_kyc_url(company), {"status_code": "L2_VERIFIED"}, format="json").status_code == 403


def test_http_moderator_can_force_approve_but_not_verify_or_bill(make_operator, company, subscription, quote):
    client = _auth_client(make_operator(OperatorRoleCode.MODERATOR.value))
    assert client.post(_force_approve_url(quote), {"reason": "audit override"}, format="json").status_code != 403
    assert client.post(_verify_kyc_url(company), {"status_code": "L2_VERIFIED"}, format="json").status_code == 403
    assert client.post(_activate_sub_url(subscription), {}, format="json").status_code == 403


def test_http_support_reads_users_but_writes_nothing(make_operator, company, subscription, quote):
    client = _auth_client(make_operator(OperatorRoleCode.SUPPORT.value))
    assert client.get(_users_list_url()).status_code == 200
    assert client.post(_verify_kyc_url(company), {"status_code": "L2_VERIFIED"}, format="json").status_code == 403
    assert client.post(_activate_sub_url(subscription), {}, format="json").status_code == 403
    assert client.post(_force_approve_url(quote), {"reason": "x"}, format="json").status_code == 403


def test_http_super_operator_passes_every_gate(make_operator, company, subscription, quote):
    client = _auth_client(make_operator(OperatorRoleCode.SUPER_OPERATOR.value))
    assert client.get(_users_list_url()).status_code == 200
    assert client.post(_verify_kyc_url(company), {"status_code": "L2_VERIFIED"}, format="json").status_code != 403
    assert client.post(_activate_sub_url(subscription), {}, format="json").status_code != 403
    assert client.post(_force_approve_url(quote), {"reason": "audit override"}, format="json").status_code != 403


# ══════════════════════════════════════════════════════════════════════════
# GROUP C — operator-role management service (Rule 8) + never-orphan floor
# ══════════════════════════════════════════════════════════════════════════


def test_create_operator_role_requires_super_operator(make_operator):
    support = make_operator(OperatorRoleCode.SUPPORT.value)
    role, err = services.create_operator_role(support, "Аудитор платформы", [OperatorPermission.USERS_VIEW.value])
    assert role is None
    assert err == "ONLY_SUPER_OPERATOR_CAN_MANAGE_OPERATORS"


def test_super_operator_can_create_role(make_operator):
    super_op = make_operator(OperatorRoleCode.SUPER_OPERATOR.value)
    role, err = services.create_operator_role(super_op, "Аудитор платформы", [OperatorPermission.USERS_VIEW.value])
    assert err is None
    assert role is not None
    assert role.is_system is False
    assert role.permissions == [OperatorPermission.USERS_VIEW.value]


def test_update_system_operator_role_is_immutable(make_operator, operator_roles):
    super_op = make_operator(OperatorRoleCode.SUPER_OPERATOR.value)
    system_role = operator_roles[OperatorRoleCode.SUPER_OPERATOR.value]
    role, err = services.update_operator_role(super_op, system_role, "Renamed", [OperatorPermission.USERS_VIEW.value])
    assert role is None
    assert err == "SYSTEM_OPERATOR_ROLE_IMMUTABLE"


def test_delete_system_operator_role_is_immutable(make_operator, operator_roles):
    super_op = make_operator(OperatorRoleCode.SUPER_OPERATOR.value)
    system_role = operator_roles[OperatorRoleCode.SUPER_OPERATOR.value]
    err = services.delete_operator_role(super_op, system_role)
    assert err == "SYSTEM_OPERATOR_ROLE_IMMUTABLE"


def test_assign_operator_role_to_another_operator(make_operator, operator_roles):
    super_op = make_operator(OperatorRoleCode.SUPER_OPERATOR.value)
    target = make_operator(OperatorRoleCode.KYC_OFFICER.value)
    support_role = operator_roles[OperatorRoleCode.SUPPORT.value]
    updated, err = services.assign_operator_role(super_op, target.id, support_role.id)
    assert err is None
    assert updated.operator_role_id == support_role.id


def test_assign_operator_role_rejects_non_operator(make_operator, operator_roles, normal_user):
    super_op = make_operator(OperatorRoleCode.SUPER_OPERATOR.value)
    support_role = operator_roles[OperatorRoleCode.SUPPORT.value]
    updated, err = services.assign_operator_role(super_op, normal_user.id, support_role.id)
    assert updated is None
    assert err == "NOT_A_PLATFORM_OPERATOR"


def test_never_orphan_blocks_demoting_the_last_operator_manager(make_operator, operator_roles):
    # Exactly ONE active operator holding operators.manage exists (the sole SUPER_OPERATOR).
    sole_super = make_operator(OperatorRoleCode.SUPER_OPERATOR.value)
    support_role = operator_roles[OperatorRoleCode.SUPPORT.value]
    updated, err = services.assign_operator_role(sole_super, sole_super.id, support_role.id)
    assert updated is None
    assert err == "CANNOT_DEMOTE_LAST_OPERATOR"
    sole_super.refresh_from_db()
    assert sole_super.operator_role.code == OperatorRoleCode.SUPER_OPERATOR.value


def test_never_orphan_allows_demotion_when_a_second_manager_exists(make_operator, operator_roles):
    super_op_1 = make_operator(OperatorRoleCode.SUPER_OPERATOR.value)
    super_op_2 = make_operator(OperatorRoleCode.SUPER_OPERATOR.value)
    support_role = operator_roles[OperatorRoleCode.SUPPORT.value]
    updated, err = services.assign_operator_role(super_op_2, super_op_1.id, support_role.id)
    assert err is None
    assert updated.operator_role_id == support_role.id


# ══════════════════════════════════════════════════════════════════════════
# GROUP D — adversarial-review regressions (2026-06-28 security pass):
#   (1) a narrow operator must NOT edit company data via the member-action bypass;
#   (2)+(3) the operator-plane never-orphan floor must hold across change_user_role
#       and toggle_user_active, not just assign_operator_role.
# ══════════════════════════════════════════════════════════════════════════


def _company_detail_url(company):
    from django.urls import reverse

    return reverse("company-detail", kwargs={"pk": company.pk})


def test_http_support_cannot_edit_company_via_member_bypass(make_operator, company):
    """A SUPPORT operator (companies.view only) must be blocked from PATCHing a company —
    update/partial_update are member-allowed but an OPERATOR still hits OperatorScoped."""
    client = _auth_client(make_operator(OperatorRoleCode.SUPPORT.value))
    resp = client.patch(_company_detail_url(company), {"name": "Hijacked Name"}, format="json")
    assert resp.status_code == 403


def test_http_super_operator_can_edit_company(make_operator, company):
    client = _auth_client(make_operator(OperatorRoleCode.SUPER_OPERATOR.value))
    resp = client.patch(_company_detail_url(company), {"contact_person": "New Contact"}, format="json")
    assert resp.status_code != 403


def _team_action_url(company, name):
    from django.urls import reverse

    return reverse(name, kwargs={"pk": company.pk})


def test_http_support_cannot_manage_team_via_operator_bypass(make_operator, company):
    """SEC audit #8: team-management actions (invite / set-member-role / update-member-
    capabilities) are member-facing but reachable by a platform operator — a SUPPORT role
    (no users.manage) must be refused, not waved through by the operator_permissions gap."""
    client = _auth_client(make_operator(OperatorRoleCode.SUPPORT.value))
    assert (
        client.post(_team_action_url(company, "company-invite"), {"email": "x@y.test"}, format="json").status_code
        == 403
    )
    assert (
        client.post(
            _team_action_url(company, "company-set-member-role"), {"member_id": 1, "role": "OWNER"}, format="json"
        ).status_code
        == 403
    )
    assert (
        client.post(
            _team_action_url(company, "company-update-member-capabilities"),
            {"member_id": 1, "can_sell": True},
            format="json",
        ).status_code
        == 403
    )


def test_http_super_operator_may_manage_team(make_operator, company):
    """SUPER_OPERATOR holds users.manage → passes the OperatorScoped gate (the action may then
    400/404 on the bogus member id, but that is NOT a 403 permission refusal)."""
    client = _auth_client(make_operator(OperatorRoleCode.SUPER_OPERATOR.value))
    assert (
        client.post(
            _team_action_url(company, "company-update-member-capabilities"),
            {"member_id": 999999, "can_sell": True},
            format="json",
        ).status_code
        != 403
    )


def test_change_user_role_blocks_demoting_the_last_operator_manager(make_operator, system_role_factory):
    system_role_factory(code="USER", name="Пользователь")
    sole_super = make_operator(OperatorRoleCode.SUPER_OPERATOR.value)
    updated, err = services.change_user_role(sole_super, "USER")
    assert updated is None
    assert err == "CANNOT_DEMOTE_LAST_OPERATOR_MANAGER"
    sole_super.refresh_from_db()
    assert sole_super.role.code == "ADMIN"


def test_change_user_role_allows_demotion_when_a_second_manager_exists(make_operator, system_role_factory):
    system_role_factory(code="USER", name="Пользователь")
    make_operator(OperatorRoleCode.SUPER_OPERATOR.value)  # a second manager
    demote_me = make_operator(OperatorRoleCode.SUPER_OPERATOR.value)
    updated, err = services.change_user_role(demote_me, "USER")
    assert err is None
    assert updated.role.code == "USER"


def test_toggle_active_blocks_deactivating_the_last_operator_manager(make_operator):
    requester = make_operator(OperatorRoleCode.SUPER_OPERATOR.value)
    sole_super = make_operator(OperatorRoleCode.SUPER_OPERATOR.value)
    # `requester` is a second manager, so deactivating it is allowed; deactivating the
    # remaining sole manager must then be blocked.
    _, err1 = services.toggle_user_active(requester, sole_super)
    assert err1 is None
    _, err2 = services.toggle_user_active(sole_super, requester)
    assert err2 == "CANNOT_DEACTIVATE_SOLE_OPERATOR"
    sole_super.refresh_from_db()
    assert sole_super.is_active is True
