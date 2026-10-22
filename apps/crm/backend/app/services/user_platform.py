"""Роли Платформы в изменениях пользователя (CRM-01; вынесено из `services/users.py`, ≤ 400 строк).

Непустые `platform_roles` вычисляют роль CRM, `platform_access` и `erp_role_codes` — ручные значения
в том же запросе игнорируются. Снятие всех ролей Платформы снимает и выданный ими доступ: без явных
ручных значений в запросе пользователь становится `viewer` только с CRM и без ролей ERP.
"""

from collections.abc import Sequence
from dataclasses import replace
from typing import TYPE_CHECKING

from app.domain.errors import ValidationFailedError
from app.domain.platform_roles import derive_access, normalize_platform_roles, normalize_position

if TYPE_CHECKING:
    from app.services.users import UserPatch

DEFAULT_ROLES = ["viewer"]


def checked_platform_roles(codes: Sequence[str]) -> list[str]:
    try:
        return normalize_platform_roles(codes)
    except ValueError as exc:
        raise ValidationFailedError(str(exc), field="platform_roles") from exc


def checked_position(value: str | None) -> str | None:
    try:
        return normalize_position(value)
    except ValueError as exc:
        raise ValidationFailedError(str(exc), field="position") from exc


def resolve_patch(current: Sequence[str], patch: "UserPatch") -> "UserPatch":
    """Патч с вычисленными ролями CRM, доступом и ролями ERP, если роли Платформы управляют ими."""
    requested = (
        None if patch.platform_roles is None else checked_platform_roles(patch.platform_roles)
    )
    effective = list(current) if requested is None else requested
    if effective:
        derived = derive_access(effective)
        return replace(
            patch,
            platform_roles=requested,
            roles=[derived.crm_role],
            platform_access=list(derived.platform_access),
            erp_role_codes=list(derived.erp_role_codes),
        )
    if requested is not None and current:  # роли Платформы сняли
        return replace(
            patch,
            platform_roles=requested,
            roles=patch.roles or DEFAULT_ROLES,
            platform_access=patch.platform_access or ["crm"],
            erp_role_codes=patch.erp_role_codes or [],
        )
    return replace(patch, platform_roles=requested)
