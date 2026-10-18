"""Роли бэк-офиса (Role + набор прав) — сервисный слой (M1-ERP-05).

Системные роли-шаблоны (`BackofficeRoleCode`, BUSINESS §11) сеются для своей компании и не
меняются; свои роли создаёт сотрудник с правом `team.manage`. Сотруднику можно выдать
несколько ролей — права складываются. «Администратор» — не роль, а `is_superuser`.
"""

from typing import Iterable, List, Optional, Tuple

from django.db import transaction
from django.db.models import Case, Count, IntegerField, Value, When

from ..constants import ALL_PERMISSIONS, ROLE_TEMPLATES, BackofficeRoleCode, Permission
from ..models import CompanyMember, CompanyRole, CustomUser
from .permissions import member_has_permission

# Должность приглашения (WorkspaceRole) → стартовые роли бэк-офиса. Должность доступа не даёт —
# это только подсказка, с какими ролями человек приходит; поправить можно в «Команде и ролях».
_WORKSPACE_TO_ROLES = {
    "OWNER": [BackofficeRoleCode.HEAD],
    "DIRECTOR": [BackofficeRoleCode.HEAD],
    "SALES_MANAGER": [BackofficeRoleCode.CALCULATION],
    "CONTRACT_MANAGER": [BackofficeRoleCode.CALCULATION],
    "FOREIGN_TRADE_SPECIALIST": [BackofficeRoleCode.CALCULATION],
    "PROCUREMENT_MANAGER": [BackofficeRoleCode.CATALOG_SUPPLY],
    "LOGIST": [BackofficeRoleCode.FULFILLMENT],
    "ACCOUNTANT": [BackofficeRoleCode.FINANCE],
}


def _is_own_company(company_id) -> bool:
    from core.tenant import own_company_id

    return bool(company_id) and company_id == own_company_id()


def ensure_default_company_roles(company) -> dict:
    """Системные роли своей компании (идемпотентно), `{code: CompanyRole}`.

    Права системной роли всегда равны шаблону в коде (`ROLE_TEMPLATES`): новый код права,
    добавленный в шаблон, доезжает до роли при следующем вызове. Роль компании с тем же именем,
    но без кода, становится системной (так миграция приняла старые «Финансы» и «Наблюдатель»).
    """
    roles = {}
    for code, label in BackofficeRoleCode.choices:
        perms = list(ROLE_TEMPLATES[code])
        role = CompanyRole.objects.filter(company=company, code=code).first()
        if role is None:
            role = CompanyRole.objects.filter(company=company, name=label, code="").first()
        if role is None:
            role = CompanyRole.objects.create(company=company, code=code, name=label, permissions=perms, is_system=True)
        elif role.code != code or role.permissions != perms or not role.is_system:
            role.code, role.permissions, role.is_system = code, perms, True
            role.save(update_fields=["code", "permissions", "is_system", "updated_at"])
        roles[code] = role
    return roles


def default_roles_for(company, workspace_role_code: str) -> List[CompanyRole]:
    """Стартовые роли нового сотрудника своей компании по должности приглашения; для компании-
    клиента — пусто (клиентских аккаунтов в ERP нет, FIX-13)."""
    if not _is_own_company(company.id):
        return []
    roles = ensure_default_company_roles(company)
    codes = _WORKSPACE_TO_ROLES.get(workspace_role_code, [BackofficeRoleCode.VIEWER])
    return [roles[code] for code in codes]


def grant_default_roles(membership: CompanyMember, workspace_role_code: str) -> None:
    """Выдать стартовые роли, если у участника ещё нет ни одной (повторное добавление не трогает
    роли, назначенные вручную)."""
    if membership.company_roles.exists():
        return
    roles = default_roles_for(membership.company, workspace_role_code)
    if roles:
        membership.company_roles.add(*roles)


def list_roles_for_user(user: "CustomUser"):
    """Роли своей компании (системные — первыми). Только сотрудникам и администратору."""
    from core.tenant import own_company

    company = own_company()
    if company is None or not (user.is_superuser or user.memberships.filter(company=company, is_active=True).exists()):
        return CompanyRole.objects.none()
    ensure_default_company_roles(company)
    # Системные — в порядке BUSINESS §11 (Расчёт → … → Наблюдатель), затем свои по имени.
    template_order = Case(
        *[When(code=code, then=Value(index)) for index, code in enumerate(BackofficeRoleCode.values)],
        default=Value(len(BackofficeRoleCode.values)),
        output_field=IntegerField(),
    )
    return (
        CompanyRole.objects.filter(company=company)
        .annotate(member_count=Count("members", distinct=True), template_order=template_order)
        .order_by("template_order", "name")
    )


def _can_manage(user, company_id) -> bool:
    return member_has_permission(user, company_id, Permission.TEAM_MANAGE)


def _validate_perms(permissions) -> Tuple[Optional[list], Optional[str]]:
    if not isinstance(permissions, (list, tuple)):
        return None, "UNKNOWN_PERMISSION_CODE"
    perms = list(dict.fromkeys(permissions))
    if any(p not in ALL_PERMISSIONS for p in perms):
        return None, "UNKNOWN_PERMISSION_CODE"
    return perms, None


@transaction.atomic
def create_company_role(user, company_id, name, permissions) -> Tuple[Optional[CompanyRole], Optional[str]]:
    if not _is_own_company(company_id):
        return None, "ROLE_COMPANY_MISMATCH"
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
    new_name = (name or role.name).strip()
    if CompanyRole.objects.filter(company_id=role.company_id, name__iexact=new_name).exclude(pk=role.pk).exists():
        return None, "ROLE_NAME_TAKEN"
    role.name = new_name
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


def _parse_role_ids(role_ids) -> Optional[List[int]]:
    if not isinstance(role_ids, (list, tuple)):
        return None
    try:
        return list(dict.fromkeys(int(rid) for rid in role_ids))
    except (TypeError, ValueError):
        return None


@transaction.atomic
def set_member_roles(user, member_id, role_ids: Iterable) -> Tuple[Optional[CompanyMember], Optional[str]]:
    """Заменить набор ролей сотрудника своей компании (`role_ids` — полный новый набор).

    Защита от тупика: нельзя снять с самого себя `team.manage` — иначе управлять командой стало бы
    некому, кроме администратора (суперпользователя из CRM)."""
    ids = _parse_role_ids(role_ids)
    if ids is None:
        return None, "ROLE_IDS_REQUIRED"
    member = CompanyMember.objects.filter(pk=member_id).select_related("company").first()
    if member is None:
        return None, "MEMBER_NOT_FOUND"
    if not _is_own_company(member.company_id):
        return None, "ROLE_COMPANY_MISMATCH"
    if not _can_manage(user, member.company_id):
        return None, "ONLY_TEAM_MANAGER_CAN_MANAGE_ROLES"
    roles = list(CompanyRole.objects.filter(pk__in=ids))
    if len(roles) != len(ids):
        return None, "ROLE_NOT_FOUND"
    if any(role.company_id != member.company_id for role in roles):
        return None, "ROLE_COMPANY_MISMATCH"
    keeps_team_manage = any(role.has_perm(Permission.TEAM_MANAGE) for role in roles)
    if member.user_id == user.pk and not user.is_superuser and not keeps_team_manage:
        return None, "CANNOT_DROP_OWN_TEAM_MANAGE"
    member.company_roles.set(roles)
    return member, None
