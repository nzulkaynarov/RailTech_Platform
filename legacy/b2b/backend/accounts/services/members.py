import logging
from typing import Optional, Tuple

from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
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

    CompanyMember.objects.create(user=user, company=company, role=w_role, is_primary=True)

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
    return membership, None


def company_active_admins(company: Company):
    """Active members holding the full-admin workspace role (code OWNER).

    OWNER is the internal code; its display label is «Администратор компании».
    This is the company's irreducible admin set — see remove_company_member.
    """
    return CompanyMember.objects.filter(company=company, is_active=True, role__code=WorkspaceRoleCode.OWNER)


def remove_company_member(
    membership: "CompanyMember",
) -> Tuple[Optional[bool], Optional[str]]:
    """
    Remove a member, enforcing the never-orphan invariant.

    A company must ALWAYS keep at least one active admin (OWNER) — the party
    accountable for KYC/billing. Removing the last one would orphan the company,
    so it's refused; the admin role must be transferred first.
    """
    is_admin = membership.is_active and membership.role_id and membership.role.code == WorkspaceRoleCode.OWNER
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
      - never-orphan: the LAST active admin (OWNER) cannot be demoted away from
        OWNER (transfer/promote someone else first) → CANNOT_DEMOTE_LAST_COMPANY_ADMIN.
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

    currently_admin = membership.is_active and membership.role_id and membership.role.code == WorkspaceRoleCode.OWNER
    if currently_admin and role.code != WorkspaceRoleCode.OWNER:
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
    # they are the SOLE active OWNER of any company, that company would be left with no admin
    # (no one to manage team/KYC/billing). Block — transfer ownership first.
    if user.is_active:  # about to deactivate
        owner_memberships = CompanyMember.objects.filter(
            user=user, is_active=True, role__code=WorkspaceRoleCode.OWNER
        ).select_related("company")
        for membership in owner_memberships:
            if not company_active_admins(membership.company).exclude(user=user).exists():
                return None, "CANNOT_DEACTIVATE_SOLE_COMPANY_ADMIN"
    user.is_active = not user.is_active
    user.save(update_fields=["is_active"])
    return user, None
