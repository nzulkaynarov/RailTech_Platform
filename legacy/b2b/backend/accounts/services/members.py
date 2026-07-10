import logging
from typing import Optional, Tuple

from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.db.models import Q
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from notifications.emails import send_templated_email

from ..constants import WorkspaceRoleCode
from ..models import Company, CompanyMember, CustomUser, SystemRole, WorkspaceRole

logger = logging.getLogger(__name__)


def invite_workspace_member(company: Company, email: str, role_code: str) -> Tuple[Optional[CustomUser], Optional[str]]:
    if not email:
        return None, "EMAIL_REQUIRED"

    if CustomUser.objects.filter(email=email).exists():
        return None, "USER_EMAIL_ALREADY_EXISTS"

    w_role = WorkspaceRole.objects.filter(code=role_code).first()
    if not w_role:
        return None, "SYSTEM_ROLE_NOT_FOUND"

    # Default system role for invited member: USER (пользователь компании).
    user_role = SystemRole.objects.filter(code="USER").first()

    user = CustomUser.objects.create(
        username=email,
        email=email,
        is_active=False,
        role=user_role,
    )
    user.set_unusable_password()
    user.save()

    member = CompanyMember.objects.create(user=user, company=company, role=w_role, is_primary=True)
    # Give the invited member a starting CompanyRole mapped from their WorkspaceRole, so the G4
    # access matrix governs them from day one (not the can_sell/can_buy fallback). The company
    # admin can re-assign later in «Команда и доступы».
    from .roles import default_company_role_for

    member.company_role = default_company_role_for(company, role_code)
    member.save(update_fields=["company_role"])

    token = default_token_generator.make_token(user)
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    base_url = settings.FRONTEND_URL
    setup_url = f"{base_url}/setup-password?uid={uid}&token={token}"

    send_templated_email(
        "invite_member",
        {"company_name": company.name, "setup_url": setup_url},
        to=[email],
        channel="transactional",
        user=user,
        fail_silently=True,
    )
    return user, None


# ──────────────────────────────────────────────────────────────────────────
# Admin operations — single source of truth for business logic.
# Called from both Django Unfold actions and DRF endpoints.
# See ADR-0001 and CLAUDE.md IRON RULE 8.
# ──────────────────────────────────────────────────────────────────────────


def change_user_role(
    user: CustomUser,
    role_code: str,
) -> Tuple[Optional[CustomUser], Optional[str]]:
    """
    Change SystemRole of a user.

    Инварианты платформы:
      - ADMIN выдаётся только пользователям без активных memberships
        (Platform Admin — владелец платформы, не привязан ни к одной компании).
      - Понизить ADMIN → USER разрешено всегда.
      - USER можно выдать любому юзеру.
    """
    if not role_code:
        return None, "ROLE_CODE_REQUIRED"
    role = SystemRole.objects.filter(code=role_code).first()
    if not role:
        return None, "SYSTEM_ROLE_NOT_FOUND"
    if role.code == "ADMIN":
        has_active_memberships = user.memberships.filter(is_active=True).exists()
        if has_active_memberships:
            return None, "ADMIN_ROLE_REQUIRES_NO_MEMBERSHIPS"
    else:
        # Demoting ADMIN→USER flips is_platform_admin off and strips operator capability.
        # Operator-plane never-orphan (ADR-0004 G1): refuse if this is the last operator who
        # can administer operator roles — reassign operator management first.
        from .operators import is_last_operator_manager

        if is_last_operator_manager(user):
            return None, "CANNOT_DEMOTE_LAST_OPERATOR_MANAGER"
    user.role = role
    user.save(update_fields=["role"])
    return user, None


def add_company_member(
    user: CustomUser,
    company: Company,
    workspace_role_code: str,
    is_primary: bool = False,
) -> Tuple[Optional["CompanyMember"], Optional[str]]:
    """
    Add or update a CompanyMember link between user and company.

    Инварианты платформы:
      - Platform Admin (role=ADMIN) не может быть членом компании.
      - workspace_role должен быть применим к типам компании (applicable_to_types).
    """
    if user.role and user.role.code == "ADMIN":
        return None, "PLATFORM_ADMIN_CANNOT_JOIN_COMPANY"
    role = WorkspaceRole.objects.filter(code=workspace_role_code).first()
    if not role:
        return None, "WORKSPACE_ROLE_NOT_FOUND"
    applicable = role.applicable_to_types.all()
    if applicable.exists():
        company_type_codes = set(company.types.values_list("code", flat=True))
        allowed_codes = set(applicable.values_list("code", flat=True))
        if not (company_type_codes & allowed_codes):
            return None, "WORKSPACE_ROLE_NOT_APPLICABLE_TO_COMPANY_TYPE"
    membership, _created = CompanyMember.objects.update_or_create(
        user=user,
        company=company,
        defaults={"role": role, "is_primary": is_primary, "is_active": True},
    )
    # Seed the permission-engine CompanyRole exactly like invite_workspace_member /
    # submit_company_profile do, so this operator path stops minting permission-less
    # company_role=NULL members (which the G4 permission engine can only serve via the
    # shrinking legacy fallback). Only when missing — never clobber an admin's custom
    # role assignment on a re-add.
    if membership.company_role_id is None:
        from .roles import default_company_role_for

        membership.company_role = default_company_role_for(company, workspace_role_code)
        membership.save(update_fields=["company_role"])
    return membership, None


def _admin_floor_q() -> "Q":
    """The never-orphan admin floor as ONE reusable predicate (ADR-0005 Phase E U3).

    A member counts as a company admin if they hold the immutable is_system
    «Администратор компании» CompanyRole — the SAME floor `roles.py` enforces on
    CompanyRole reassignment — OR, during the WorkspaceRole→CompanyRole transition,
    they are an un-migrated legacy OWNER (company_role IS NULL). The legacy clause is
    what keeps never-orphan protecting tenants whose members predate the 0030 backfill:
    without it, deleting/deactivating the sole legacy OWNER (whose admin rights come
    from member_has_permission's OWNER fallback) would silently orphan the company.
    Unifying every never-orphan check on this predicate removes the two-definitions
    divergence window the deprecation ADR called out.
    """
    return Q(company_role__is_system=True) | Q(company_role__isnull=True, role__code=WorkspaceRoleCode.OWNER)


def company_active_admins(company: Company):
    """The company's irreducible admin set for the never-orphan invariant.

    See `_admin_floor_q` for the unified definition. Used by remove_company_member,
    set_member_workspace_role and toggle_user_active — all share this one query.
    """
    return CompanyMember.objects.filter(_admin_floor_q(), company=company, is_active=True)


def remove_company_member(
    membership: "CompanyMember",
) -> Tuple[Optional[bool], Optional[str]]:
    """
    Remove a member, enforcing the never-orphan invariant.

    A company must ALWAYS keep at least one active admin — the party accountable
    for KYC/billing. Removing the last one would orphan the company, so it's
    refused; the admin role must be transferred first. "Admin" is the unified
    is_system / legacy-OWNER floor (see `_admin_floor_q`).
    """
    is_admin = membership.is_active and company_active_admins(membership.company).filter(pk=membership.pk).exists()
    if is_admin:
        other_admins = company_active_admins(membership.company).exclude(pk=membership.pk)
        if not other_admins.exists():
            return None, "CANNOT_REMOVE_LAST_COMPANY_ADMIN"
    membership.delete()
    return True, None


def set_member_workspace_role(
    membership: "CompanyMember",
    role_code: str,
) -> Tuple[Optional["CompanyMember"], Optional[str]]:
    """
    Change a member's workspace role — the Company Admin's delegation tool.

    Invariants:
      - role must exist and be applicable to the company's type(s);
      - never-orphan: if this member is the company's SOLE admin (unified floor,
        see `_admin_floor_q`) and the new WorkspaceRole would strip their admin
        standing, refuse → CANNOT_DEMOTE_LAST_COMPANY_ADMIN (transfer first). A
        member on the is_system CompanyRole keeps admin standing regardless of the
        WorkspaceRole label, so relabeling them is never blocked.
    """
    role = WorkspaceRole.objects.filter(code=role_code).first()
    if not role:
        return None, "WORKSPACE_ROLE_NOT_FOUND"

    applicable = role.applicable_to_types.all()
    if applicable.exists():
        company_type_codes = set(membership.company.types.values_list("code", flat=True))
        allowed_codes = set(applicable.values_list("code", flat=True))
        if not (company_type_codes & allowed_codes):
            return None, "WORKSPACE_ROLE_NOT_APPLICABLE_TO_COMPANY_TYPE"

    currently_admin = (
        membership.is_active and company_active_admins(membership.company).filter(pk=membership.pk).exists()
    )
    would_stay_admin = bool(
        (membership.company_role_id and membership.company_role.is_system) or role.code == WorkspaceRoleCode.OWNER
    )
    if currently_admin and not would_stay_admin:
        other_admins = company_active_admins(membership.company).exclude(pk=membership.pk)
        if not other_admins.exists():
            return None, "CANNOT_DEMOTE_LAST_COMPANY_ADMIN"

    membership.role = role
    membership.save(update_fields=["role"])
    return membership, None


def toggle_user_active(
    user: CustomUser,
    requester: CustomUser,
) -> Tuple[Optional[CustomUser], Optional[str]]:
    """
    Toggle user's is_active flag. Prevents self-deactivation.
    Returns: (user, error_or_None)
    """
    if user.pk == requester.pk:
        return None, "CANNOT_DEACTIVATE_SELF"
    # Never-orphan (audit L3): deactivating the user disables their account platform-wide; if
    # they are the SOLE active admin of any company, that company would be left with no admin
    # (no one to manage team/KYC/billing). Block — transfer ownership first. "Admin" is the
    # unified is_system / legacy-OWNER floor (see `_admin_floor_q`), matching every other check.
    if user.is_active:  # about to deactivate
        admin_memberships = CompanyMember.objects.filter(_admin_floor_q(), user=user, is_active=True).select_related(
            "company"
        )
        for membership in admin_memberships:
            if not company_active_admins(membership.company).exclude(user=user).exists():
                return None, "CANNOT_DEACTIVATE_SOLE_COMPANY_ADMIN"
        # Operator-plane never-orphan (ADR-0004 G1): deactivating the sole operator who can
        # administer operator roles would orphan the operator plane — reassign first.
        from .operators import is_last_operator_manager

        if is_last_operator_manager(user):
            return None, "CANNOT_DEACTIVATE_SOLE_OPERATOR"
    user.is_active = not user.is_active
    user.save(update_fields=["is_active"])
    return user, None
