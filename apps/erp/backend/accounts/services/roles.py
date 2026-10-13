"""Company role (Role+Permission-set) management — Rule 8 service layer.

The company admin (team.manage) creates/edits company-scoped roles and assigns them to
members. The system "Company administrator" role is immutable. See
Docs/old/specs/rbac-roles-design-2026-06-25.md.
"""

from typing import Optional, Tuple

from django.db import transaction
from django.db.models import Count

from ..constants import ALL_PERMISSIONS, COMPANY_ADMIN_ROLE_NAME, ROLE_TEMPLATES
from ..models import CompanyMember, CompanyRole, CustomUser
from .permissions import member_has_permission

# Legacy WorkspaceRole.code → default CompanyRole template name (mirror of migration 0023's
# ROLE_MAP, kept as the runtime source so a member invited by WorkspaceRole gets a sane
# starting CompanyRole). Unknown codes → «Наблюдатель» (no permissions).
_WORKSPACE_TO_ROLE = {
    "OWNER": COMPANY_ADMIN_ROLE_NAME,
    "DIRECTOR": COMPANY_ADMIN_ROLE_NAME,
    "SALES_MANAGER": "Менеджер по продажам",
    "LOGIST": "Менеджер по продажам",
    "CONTRACT_MANAGER": "Менеджер по продажам",
    "FOREIGN_TRADE_SPECIALIST": "Менеджер по продажам",
    "PROCUREMENT_MANAGER": "Менеджер закупок",
    "BUYER_MANAGER": "Менеджер закупок",
}


def ensure_default_company_roles(company) -> dict:
    """Seed the starting CompanyRole templates for a company (idempotent), returning
    {name: CompanyRole}. Migration 0023 seeded only companies existing at migration time —
    tenants registered AFTER it had NO roles, so the assign dropdown was empty and the G4
    permission engine was silently bypassed (every member fell to the can_sell/can_buy
    fallback). Call this on every company creation so new tenants match the seeded ones."""
    roles = {}
    for name, perms in ROLE_TEMPLATES.items():
        roles[name] = CompanyRole.objects.get_or_create(
            company=company,
            name=name,
            defaults={"permissions": list(perms), "is_system": name == COMPANY_ADMIN_ROLE_NAME},
        )[0]
    return roles


def default_company_role_for(company, workspace_role_code: str) -> CompanyRole:
    """The seeded CompanyRole a member with this WorkspaceRole should start with (seeding the
    company's default roles first if needed)."""
    roles = ensure_default_company_roles(company)
    name = _WORKSPACE_TO_ROLE.get(workspace_role_code, "Наблюдатель")
    return roles.get(name) or roles[COMPANY_ADMIN_ROLE_NAME]


def _seller_or_admin_company_ids(user: "CustomUser") -> list:
    return list(user.memberships.filter(is_active=True).values_list("company_id", flat=True))


def list_roles_for_user(user: "CustomUser"):
    """Roles of the requester's OWN companies only (confidentiality)."""
    ids = _seller_or_admin_company_ids(user)
    if not ids:
        return CompanyRole.objects.none()
    return (
        CompanyRole.objects.filter(company_id__in=ids)
        .annotate(member_count=Count("members"))
        .order_by("-is_system", "name")
    )


def _can_manage(user, company_id) -> bool:
    return member_has_permission(user, company_id, "team.manage")


def _validate_perms(permissions) -> Tuple[Optional[list], Optional[str]]:
    perms = list(permissions or [])
    if any(p not in ALL_PERMISSIONS for p in perms):
        return None, "UNKNOWN_PERMISSION_CODE"
    return perms, None


@transaction.atomic
def create_company_role(user, company_id, name, permissions) -> Tuple[Optional[CompanyRole], Optional[str]]:
    if not _can_manage(user, company_id):
        return None, "ONLY_TEAM_MANAGER_CAN_MANAGE_ROLES"
    name = (name or "").strip()
    if not name:
        return None, "ROLE_NAME_REQUIRED"
    perms, err = _validate_perms(permissions)
    if err:
        return None, err
    if CompanyRole.objects.filter(company_id=company_id, name__iexact=name).exists():
        return None, "ROLE_NAME_TAKEN"
    role = CompanyRole.objects.create(
        company_id=company_id, name=name, permissions=perms, is_system=False, created_by=user
    )
    return role, None


@transaction.atomic
def update_company_role(user, role: CompanyRole, name, permissions) -> Tuple[Optional[CompanyRole], Optional[str]]:
    if not _can_manage(user, role.company_id):
        return None, "ONLY_TEAM_MANAGER_CAN_MANAGE_ROLES"
    if role.is_system:
        return None, "SYSTEM_ROLE_IMMUTABLE"
    perms, err = _validate_perms(permissions)
    if err:
        return None, err
    role.name = (name or role.name).strip()
    role.permissions = perms
    role.save(update_fields=["name", "permissions", "updated_at"])
    return role, None


@transaction.atomic
def delete_company_role(user, role: CompanyRole) -> Optional[str]:
    if not _can_manage(user, role.company_id):
        return "ONLY_TEAM_MANAGER_CAN_MANAGE_ROLES"
    if role.is_system:
        return "SYSTEM_ROLE_IMMUTABLE"
    if role.members.exists():
        return "ROLE_HAS_MEMBERS_REASSIGN_FIRST"
    role.delete()
    return None


@transaction.atomic
def assign_role_to_member(user, member_id, role_id) -> Tuple[Optional[CompanyMember], Optional[str]]:
    member = CompanyMember.objects.filter(pk=member_id).select_related("company", "company_role").first()
    if member is None:
        return None, "MEMBER_NOT_FOUND"
    if not _can_manage(user, member.company_id):
        return None, "ONLY_TEAM_MANAGER_CAN_MANAGE_ROLES"
    role = CompanyRole.objects.filter(pk=role_id).first()
    if role is None:
        return None, "ROLE_NOT_FOUND"
    if role.company_id != member.company_id:
        return None, "ROLE_COMPANY_MISMATCH"
    # Never-orphan invariant (ADR-0004 / ADR-0005 U3): a company must always keep ≥1 active
    # admin. Reassigning to a non-system role drops this member from the admin floor, so block
    # when they are the company's SOLE admin. The floor is the UNIFIED predicate (members.
    # _admin_floor_q): is_system CompanyRole OR an un-migrated legacy OWNER (company_role IS
    # NULL). Checking only is_system here missed a sole legacy OWNER — reassigning them to a
    # permission-less role orphaned the company (they lose the OWNER permission fallback and no
    # longer count as admin under either clause).
    if not role.is_system:
        from .members import company_active_admins

        admins = company_active_admins(member.company)
        if admins.filter(pk=member.pk).exists() and not admins.exclude(pk=member.pk).exists():
            return None, "CANNOT_DEMOTE_LAST_COMPANY_ADMIN"
    member.company_role = role
    member.save(update_fields=["company_role"])
    return member, None
