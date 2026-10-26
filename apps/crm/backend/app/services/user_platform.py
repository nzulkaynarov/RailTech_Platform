"""Роли Платформы в изменениях пользователя (CRM-01 → R-1; вынесено из `services/users.py`).

Роли — данные (`platform_roles`). Непустой набор вычисляет роль CRM (для старого фронта),
`platform_access`, а права ERP считаются из матриц ролей при каждом провижининге; ручные значения
в том же запросе игнорируются. Пустой набор не принимается — 422 `roles_required` (R3-D-1): у
сотрудника хотя бы одна роль, закрыть доступ — отключить сотрудника (`is_active = false`).

Инварианты: в компании всегда есть хотя бы один активный администратор (роль `ADMIN`) и хотя бы
один активный директор (роль `DIRECTOR`, если он уже был) — иначе 409 `last_admin`/`last_director`.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.errors import (
    LastAdminError,
    LastDirectorError,
    RolesRequiredError,
    ValidationFailedError,
)
from app.domain.platform_roles import RoleGrant, derive_access, normalize_position
from app.domain.platform_roles_generated import (
    ROLE_ACCESS,
    ROLE_RESTRICTED_FIELDS,
    SYSTEM_ROLE_CODES,
)
from app.models.platform_roles import PlatformRole
from app.repositories import platform_roles as repo

if TYPE_CHECKING:
    from app.services.users import UserPatch

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


def checked_position(value: str | None) -> str | None:
    try:
        return normalize_position(value)
    except ValueError as exc:
        raise ValidationFailedError(str(exc), field="position") from exc


async def resolve_requested(
    session: AsyncSession, role_ids: Sequence[int] | None
) -> list[PlatformRole] | None:
    """Роли из запроса (`platform_role_ids`); `None` — не менять.

    Пустой набор — 422 `roles_required`, неизвестная роль — 422: код решает, не модель."""
    if role_ids is None:
        return None
    if not role_ids:
        raise RolesRequiredError(
            "an employee needs at least one platform role; deactivate the employee instead",
            field="platform_role_ids",
        )
    wanted = sorted(set(role_ids))
    found = await repo.by_ids(session, wanted)
    if len(found) != len(wanted):
        missing = sorted(set(wanted) - {r.id for r in found})
        raise ValidationFailedError(f"unknown platform roles: {missing}", field="platform_role_ids")
    return found


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
