"""Роли Платформы в изменениях пользователя (CRM-01 → R-1; вынесено из `services/users.py`).

Роли — данные (`platform_roles`). Непустой набор вычисляет роль CRM (для старого фронта),
`platform_access`, а права ERP считаются из матриц ролей при каждом провижининге; ручные значения
в том же запросе игнорируются. Снятие всех ролей снимает и выданный ими доступ: без явных ручных
значений в запросе пользователь становится `viewer` только с CRM и без ролей ERP.

Инварианты: в компании всегда есть хотя бы один активный администратор (роль `ADMIN`) и хотя бы
один активный директор (роль `DIRECTOR`, если он уже был) — иначе 409 `last_admin`/`last_director`.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.errors import LastAdminError, LastDirectorError, ValidationFailedError
from app.domain.platform_roles import (
    LEGACY_ROLE_CODES,
    RoleGrant,
    derive_access,
    legacy_code,
    normalize_platform_roles,
    normalize_position,
    role_code_for,
)
from app.domain.platform_roles_generated import (
    ROLE_ACCESS,
    ROLE_RESTRICTED_FIELDS,
    SYSTEM_ROLE_CODES,
)
from app.models.platform_roles import PlatformRole
from app.repositories import platform_roles as repo

if TYPE_CHECKING:
    from app.services.users import UserPatch

DEFAULT_ROLES = ["viewer"]
ADMIN_CODE = "ADMIN"
DIRECTOR_CODE = "DIRECTOR"


@dataclass(frozen=True, slots=True)
class RoleRef:
    """Ссылка на роль в карточке сотрудника и её матрица (матрицу отдаёт только `/me`, R-2)."""

    id: int
    name: str
    system: bool
    code: str | None = None
    access: Mapping[str, str] = field(default_factory=dict)
    restricted_fields: tuple[str, ...] = ()


def grants_of(roles: Iterable[PlatformRole]) -> list[RoleGrant]:
    return [RoleGrant(dict(r.access), tuple(r.restricted_fields), r.code) for r in roles]


def _matrix(role: PlatformRole) -> tuple[dict[str, str], tuple[str, ...]]:
    """Матрица роли: у системных — из каталога (неизменна, ADR-0012 п. 2), у прочих — данные."""
    if role.is_system and role.code in SYSTEM_ROLE_CODES:
        return dict(ROLE_ACCESS[role.code]), tuple(ROLE_RESTRICTED_FIELDS[role.code])
    return dict(role.access), tuple(role.restricted_fields)


def role_refs(roles: Iterable[PlatformRole]) -> list[RoleRef]:
    refs: list[RoleRef] = []
    for r in roles:
        access, fields = _matrix(r)
        refs.append(RoleRef(r.id, r.name, r.is_system, r.code, access, fields))
    return refs


def legacy_codes(roles: Iterable[PlatformRole]) -> list[str]:
    """Старое поле `platform_roles`: коды ролей, у которых они есть (совместимость BFF до R-2)."""
    held = {code for r in roles if (code := legacy_code(r.code))}
    return [code for code in LEGACY_ROLE_CODES if code in held]


def checked_position(value: str | None) -> str | None:
    try:
        return normalize_position(value)
    except ValueError as exc:
        raise ValidationFailedError(str(exc), field="position") from exc


async def resolve_requested(
    session: AsyncSession,
    role_ids: Sequence[int] | None,
    codes: Sequence[str] | None,
) -> list[PlatformRole] | None:
    """Роли из запроса: `platform_role_ids` или старые `platform_roles` (коды); `None` — не менять.

    Неизвестная роль — 422: код решает, не модель."""
    if role_ids is not None and codes is not None:
        raise ValidationFailedError(
            "send platform_role_ids or platform_roles, not both", field="platform_role_ids"
        )
    if role_ids is not None:
        wanted = sorted(set(role_ids))
        found = await repo.by_ids(session, wanted)
        if len(found) != len(wanted):
            missing = sorted(set(wanted) - {r.id for r in found})
            raise ValidationFailedError(
                f"unknown platform roles: {missing}", field="platform_role_ids"
            )
        return found
    if codes is not None:
        try:
            legacy = normalize_platform_roles(codes)
        except ValueError as exc:
            raise ValidationFailedError(str(exc), field="platform_roles") from exc
        found = await repo.by_codes(session, [role_code_for(c) for c in legacy])
        if len(found) != len(legacy):
            raise ValidationFailedError("platform role is not available", field="platform_roles")
        return found
    return None


def resolve_patch(
    held: Sequence[PlatformRole], requested: Sequence[PlatformRole] | None, patch: "UserPatch"
) -> "UserPatch":
    """Патч с вычисленными ролями CRM и доступом, если роли Платформы управляют ими."""
    effective = held if requested is None else requested
    if effective:
        derived = derive_access(grants_of(effective))
        return replace(
            patch,
            roles=[derived.crm_role],
            platform_access=list(derived.platform_access),
            erp_role_codes=list(derived.erp_role_codes),
        )
    if requested is not None and held:  # роли Платформы сняли
        return replace(
            patch,
            roles=patch.roles or DEFAULT_ROLES,
            platform_access=patch.platform_access or ["crm"],
            erp_role_codes=patch.erp_role_codes or [],
        )
    return patch


async def guard_system_holders(
    session: AsyncSession,
    *,
    user_id: int,
    user_active: bool,
    held: Sequence[PlatformRole],
    requested: Sequence[PlatformRole] | None,
    deactivating: bool,
) -> None:
    """Нельзя оставить компанию без активного администратора или директора (409)."""
    if not user_active:
        return  # неактивный сотрудник в счёт «последнего» не идёт
    keep = None if requested is None else {r.id for r in requested}
    for role in held:
        if not role.is_system:
            continue
        leaving = deactivating or (keep is not None and role.id not in keep)
        if leaving and await repo.count_active_holders(session, role.id, excluding=user_id) == 0:
            if role.code == ADMIN_CODE:
                raise LastAdminError("the last active administrator cannot lose the ADMIN role")
            if role.code == DIRECTOR_CODE:
                raise LastDirectorError("the last active director cannot lose the DIRECTOR role")
