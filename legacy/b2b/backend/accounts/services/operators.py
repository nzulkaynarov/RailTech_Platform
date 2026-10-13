"""Platform Operator sub-role management (ADR-0004 G1) — Rule 8 service layer.

A SUPER_OPERATOR (the `operators.manage` capability) creates/edits operator sub-roles and
assigns them to other platform operators. The seeded SUPER_OPERATOR role is immutable
(is_system). Never-orphan: the platform must always keep ≥1 active operator who can manage
operators, so the last such operator cannot be demoted. PLATFORM-scoped — no company context.
"""

from typing import Optional, Tuple

from django.db import transaction

from core.audit import log_admin_action

from ..constants import ALL_OPERATOR_PERMISSIONS, OperatorPermission, SystemRoleCode
from ..models import CustomUser, OperatorRole
from .permissions import operator_has_permission


def _slugify_code(name: str) -> str:
    from django.utils.text import slugify

    base = slugify(name, allow_unicode=False).upper().replace("-", "_")[:36] or "OPERATOR_ROLE"
    code = base
    suffix = 1
    while OperatorRole.objects.filter(code=code).exists():
        suffix += 1
        code = f"{base[:34]}_{suffix}"
    return code


def list_operator_roles():
    """All operator sub-roles with their live operator counts (for the admin UI)."""
    from django.db.models import Count

    return OperatorRole.objects.annotate(operator_count=Count("operators")).order_by("-is_system", "name")


def _can_manage(user: "CustomUser") -> bool:
    return operator_has_permission(user, OperatorPermission.OPERATORS_MANAGE)


def _validate_perms(permissions) -> Tuple[Optional[list], Optional[str]]:
    perms = list(dict.fromkeys(permissions or []))  # de-dup, preserve order
    if any(p not in ALL_OPERATOR_PERMISSIONS for p in perms):
        return None, "UNKNOWN_OPERATOR_PERMISSION_CODE"
    return perms, None


@transaction.atomic
def create_operator_role(user, name, permissions, description="") -> Tuple[Optional[OperatorRole], Optional[str]]:
    if not _can_manage(user):
        return None, "ONLY_SUPER_OPERATOR_CAN_MANAGE_OPERATORS"
    name = (name or "").strip()
    if not name:
        return None, "ROLE_NAME_REQUIRED"
    perms, err = _validate_perms(permissions)
    if err:
        return None, err
    if OperatorRole.objects.filter(name__iexact=name).exists():
        return None, "ROLE_NAME_TAKEN"
    role = OperatorRole.objects.create(
        code=_slugify_code(name),
        name=name,
        permissions=perms,
        is_system=False,
        description=(description or "").strip(),
        created_by=user,
    )
    return role, None


@transaction.atomic
def update_operator_role(
    user, role: OperatorRole, name, permissions, description=None
) -> Tuple[Optional[OperatorRole], Optional[str]]:
    if not _can_manage(user):
        return None, "ONLY_SUPER_OPERATOR_CAN_MANAGE_OPERATORS"
    if role.is_system:
        return None, "SYSTEM_OPERATOR_ROLE_IMMUTABLE"
    perms, err = _validate_perms(permissions)
    if err:
        return None, err
    role.name = (name or role.name).strip()
    role.permissions = perms
    if description is not None:
        role.description = (description or "").strip()
    role.save(update_fields=["name", "permissions", "description", "updated_at"])
    return role, None


@transaction.atomic
def delete_operator_role(user, role: OperatorRole) -> Optional[str]:
    if not _can_manage(user):
        return "ONLY_SUPER_OPERATOR_CAN_MANAGE_OPERATORS"
    if role.is_system:
        return "SYSTEM_OPERATOR_ROLE_IMMUTABLE"
    if role.operators.exists():
        return "ROLE_HAS_OPERATORS_REASSIGN_FIRST"
    role.delete()
    return None


def _is_sole_active_operator_manager(target: "CustomUser") -> bool:
    """True if `target` is the only active platform operator holding `operators.manage`
    (i.e. the only one who can administer operator roles). Demoting them would leave the
    platform with no operator-role administrator — the operator-plane never-orphan floor."""
    others = CustomUser.objects.filter(
        is_active=True,
        role__code=SystemRoleCode.ADMIN,
    ).exclude(pk=target.pk)
    for other in others.select_related("operator_role"):
        # A platform operator must have NO active memberships (invariant); skip non-operators.
        if other.memberships.filter(is_active=True).exists():
            continue
        op_role = other.operator_role
        # None → backward-compatible full access (can manage operators).
        if op_role is None or op_role.has_perm(OperatorPermission.OPERATORS_MANAGE):
            return False
    return True


def is_last_operator_manager(user: "CustomUser") -> bool:
    """True if `user` is the SOLE active platform operator who can manage operator roles.

    Demoting (ADMIN→USER), deactivating, or otherwise stripping this user would orphan the
    operator plane — no one left to administer operator roles. Used by adjacent platform
    actions (change_user_role, toggle_user_active) so EVERY path that could remove the last
    operator-manager is guarded, not just assign_operator_role.
    """
    if not user or not getattr(user, "is_active", False):
        return False
    if getattr(getattr(user, "role", None), "code", None) != SystemRoleCode.ADMIN:
        return False
    if user.memberships.filter(is_active=True).exists():
        return False  # has a company membership → not a platform operator
    op_role = getattr(user, "operator_role", None)
    user_manages = op_role is None or op_role.has_perm(OperatorPermission.OPERATORS_MANAGE)
    if not user_manages:
        return False
    return _is_sole_active_operator_manager(user)


@transaction.atomic
def assign_operator_role(user, target_user_id, role_id) -> Tuple[Optional[CustomUser], Optional[str]]:
    """Assign an operator sub-role to a platform operator. `role_id` may be None to clear
    (→ backward-compatible full access). Guards never-orphan on `operators.manage`."""
    if not _can_manage(user):
        return None, "ONLY_SUPER_OPERATOR_CAN_MANAGE_OPERATORS"
    # Lock the target row so two concurrent assigns to the SAME operator serialize — the
    # second re-evaluates the never-orphan check against the first's committed state.
    target = (
        CustomUser.objects.select_for_update(of=("self",))
        .filter(pk=target_user_id)
        .select_related("role", "operator_role")
        .first()
    )
    if target is None:
        return None, "USER_NOT_FOUND"
    if not target.is_platform_admin or getattr(getattr(target, "role", None), "code", None) != SystemRoleCode.ADMIN:
        # Operator roles only apply to platform operators (SystemRole.ADMIN, no memberships).
        return None, "NOT_A_PLATFORM_OPERATOR"

    new_role = None
    if role_id is not None:
        new_role = OperatorRole.objects.filter(pk=role_id).first()
        if new_role is None:
            return None, "ROLE_NOT_FOUND"

    # Never-orphan: don't strip the last operators.manage holder of that capability.
    currently_can_manage = target.operator_role is None or target.operator_role.has_perm(
        OperatorPermission.OPERATORS_MANAGE
    )
    will_can_manage = new_role is None or new_role.has_perm(OperatorPermission.OPERATORS_MANAGE)
    if currently_can_manage and not will_can_manage and _is_sole_active_operator_manager(target):
        return None, "CANNOT_DEMOTE_LAST_OPERATOR"

    before_code = target.operator_role.code if target.operator_role_id else ""
    target.operator_role = new_role
    target.save(update_fields=["operator_role"])
    log_admin_action(
        entity_type="user",
        entity_id=target.pk,
        action="Операторская роль изменена",
        detail=f"{target.email}: {before_code or 'полный доступ'} → {new_role.code if new_role else 'полный доступ'}",
        actor=user,
        event_code="admin.user.operator_role_changed",
        event_params={
            "email": target.email,
            "before": before_code or "",
            "after": new_role.code if new_role else "",
        },
        before={"operator_role": before_code},
        after={"operator_role": new_role.code if new_role else ""},
        # Операторская роль решает, какие чужие данные человек видит и какие
        # force-override может применить (ADR-0004 G1) — след обязателен.
        level="WARNING",
    )
    return target, None
