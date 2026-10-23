"""Срезы пользователя для сервиса и API (вынесено из `services/users.py`, ≤ 400 строк)."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime

from app.domain.erp_sync import AccessState, erp_sync_status
from app.models.auth import User
from app.models.platform_roles import PlatformRole
from app.services.user_platform import RoleRef, role_refs


@dataclass(frozen=True, slots=True)
class UserView:
    id: int
    email: str
    full_name: str
    roles: list[str]
    is_active: bool
    tg_user_id: int | None
    must_change_password: bool
    ui_mode: str
    notify_system: bool = True
    notify_leads: bool = True
    tg_dm_failed_at: datetime | None = None
    platform_access: list[str] = field(default_factory=lambda: ["crm"])
    erp_role_codes: list[str] = field(default_factory=list)
    platform_role_ids: list[int] = field(default_factory=list)
    platform_role_refs: list[RoleRef] = field(default_factory=list)
    position: str | None = None
    language: str = "ru"
    erp_sync: str = "not_applicable"
    erp_sync_error: str | None = None


@dataclass(frozen=True, slots=True)
class UserPatch:
    full_name: str | None = None
    roles: list[str] | None = None
    is_active: bool | None = None
    tg_user_id: int | None = None
    clear_tg_user_id: bool = False
    transfer_to_user_id: int | None = None
    platform_access: Sequence[str] | None = None
    erp_role_codes: Sequence[str] | None = None
    # Роли Платформы по id: `None` — не менять, `[]` — снять все.
    platform_role_ids: Sequence[int] | None = None
    position: str | None = None  # `""` очищает
    language: str | None = None  # ru|uz|en (CRM-01b); None — не менять


def view_of(
    user: User,
    roles: list[str],
    platform: Sequence[PlatformRole] = (),
    *,
    erp_pending: bool = False,
) -> UserView:
    access = list(user.platform_access or ["crm"])
    return UserView(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        roles=roles,
        is_active=user.is_active,
        tg_user_id=user.tg_user_id,
        must_change_password=user.must_change_password,
        ui_mode=user.ui_mode,
        notify_system=user.notify_system,
        notify_leads=user.notify_leads,
        tg_dm_failed_at=user.tg_dm_failed_at,
        platform_access=access,
        erp_role_codes=list(user.erp_role_codes or []),
        platform_role_ids=[r.id for r in platform],
        platform_role_refs=role_refs(platform),
        position=user.position,
        language=user.language,
        erp_sync=erp_sync_status(
            has_erp="erp" in access,
            is_active=user.is_active,
            error=user.erp_sync_error,
            pending=erp_pending,
        ),
        erp_sync_error=user.erp_sync_error,
    )


def access_state_of(view: UserView) -> AccessState:
    return AccessState(
        platform_access=tuple(view.platform_access),
        is_active=view.is_active,
        roles=tuple(view.roles),
        full_name=view.full_name,
        erp_role_codes=tuple(view.erp_role_codes),
        platform_role_ids=tuple(view.platform_role_ids),
    )


def audit_of(view: UserView) -> dict[str, object]:
    return {
        "email": view.email,
        "full_name": view.full_name,
        "roles": view.roles,
        "is_active": view.is_active,
        "tg_user_id": view.tg_user_id,
        "platform_access": view.platform_access,
        "erp_role_codes": view.erp_role_codes,
        "platform_role_ids": view.platform_role_ids,
        "platform_role_names": [r.name for r in view.platform_role_refs],
        "position": view.position,
        "language": view.language,
    }
