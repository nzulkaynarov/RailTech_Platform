"""DTO аутентификации, профиля и пользователей (SPEC §10.1)."""

from datetime import datetime
from typing import Literal, cast

from pydantic import BaseModel, Field, field_validator

from app.domain.erp_roles import ErpRoleCode, normalize_erp_roles

Role = Literal["admin", "manager", "viewer"]
PlatformSystem = Literal["crm", "erp"]
UiMode = Literal["admin", "manager"]


def _crm_only() -> list[PlatformSystem]:
    return ["crm"]


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1, max_length=256)


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105 — тип токена, не секрет
    expires_in: int
    must_change_password: bool


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=1, max_length=256)


class UserOut(BaseModel):
    id: int
    email: str
    full_name: str
    roles: list[str]
    is_active: bool
    tg_user_id: int | None
    must_change_password: bool
    ui_mode: str
    notify_system: bool
    notify_leads: bool
    # Когда Telegram последний раз отказал в личном сообщении; None — доставка работает.
    tg_dm_failed_at: datetime | None = None
    # Куда пользователю можно (FIX-11): `["crm"]` по умолчанию, `["crm", "erp"]` — доступ к ERP
    # выдан. Переход в ERP в шапке — только при "erp" (истина на сервере: без него токен — 403).
    platform_access: list[PlatformSystem] = Field(default_factory=_crm_only)
    # Системные роли бэк-офиса ERP, выданные админом (FIX-63): уходят в провижининг (`role_codes`).
    erp_role_codes: list[ErpRoleCode] = Field(default_factory=list)


class MeOut(UserOut):
    """Свой профиль + флаги развёртывания, по которым SPA прячет кнопки (истина — на сервере)."""

    # Переход в ERP по SSO включён (PLATFORM_SSO_ENABLED, FIX-03); иначе кнопки «В бэк-офис» нет.
    sso_enabled: bool = False


class MePatch(BaseModel):
    """Своё: режим навигации и подписки на личные уведомления от бота (Q-010)."""

    ui_mode: UiMode | None = None
    notify_system: bool | None = None
    notify_leads: bool | None = None


class PermissionsResponse(BaseModel):
    roles: list[str]
    permissions: dict[str, dict[str, bool]]


class UserCreate(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    full_name: str = Field(min_length=1, max_length=255)
    roles: list[Role] = Field(min_length=1)


class UserCreated(BaseModel):
    user: UserOut
    temporary_password: str = Field(description="Показывается один раз")


class UserUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=255)
    roles: list[Role] | None = Field(default=None, min_length=1)
    is_active: bool | None = None
    tg_user_id: int | None = Field(default=None, gt=0)
    clear_tg_user_id: bool = False
    # При деактивации: кому передать лидов, которых ведёт пользователь (ADR-0015).
    transfer_to_user_id: int | None = Field(default=None, gt=0)
    # Доступ к системам (FIX-11): `["crm"]` — только CRM, `["crm", "erp"]` — выдан доступ к ERP.
    # Выдача ставит в очередь провижининг в ERP, снятие — отзыв сессий ERP.
    platform_access: list[PlatformSystem] | None = None

    @field_validator("platform_access")
    @classmethod
    def _crm_is_always_there(
        cls, value: list[PlatformSystem] | None
    ) -> list[PlatformSystem] | None:
        if value is None:
            return None
        if "crm" not in value:
            raise ValueError("platform_access must include 'crm'")
        return sorted(set(value))

    # Роли ERP (FIX-63, Q-FIX50-1 (1)): полный новый набор системных ролей бэк-офиса; `[]` —
    # снять все. Изменение у пользователя с доступом к ERP — повторный провижининг; чужой код — 422.
    erp_role_codes: list[ErpRoleCode] | None = None

    @field_validator("erp_role_codes")
    @classmethod
    def _erp_roles_without_duplicates(
        cls, value: list[ErpRoleCode] | None
    ) -> list[ErpRoleCode] | None:
        if value is None:
            return None
        return cast("list[ErpRoleCode]", normalize_erp_roles(value))


class PasswordReset(BaseModel):
    temporary_password: str


class SsoTokenResponse(BaseModel):
    token: str
    redirect_url: str


class SsoExchangeRequest(BaseModel):
    token: str
