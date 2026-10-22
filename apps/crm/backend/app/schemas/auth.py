"""DTO аутентификации, профиля и пользователей (SPEC §10.1)."""

from datetime import datetime
from typing import Literal, cast

from pydantic import BaseModel, Field, field_validator, model_validator

from app.domain.erp_roles import ErpRoleCode, normalize_erp_roles
from app.domain.platform_roles import (
    POSITION_MAX_LEN,
    PlatformRoleCode,
    normalize_platform_roles,
)

Role = Literal["admin", "manager", "viewer"]
PlatformSystem = Literal["crm", "erp"]
UiMode = Literal["admin", "manager"]
Language = Literal["ru", "uz", "en"]


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


ErpSyncStatus = Literal["ok", "pending", "error", "not_applicable"]


class PlatformRoleRef(BaseModel):
    """Роль Платформы в карточке сотрудника."""

    id: int
    name: str
    system: bool
    code: str | None = None


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
    # Роли Платформы — данные (R-1, ADR-0012): непустой набор вычисляет `roles`, `platform_access`
    # и права ERP; пусто — их ведёт админ вручную. `platform_role_ids`/`platform_role_refs` — новое;
    # `platform_roles` — старое поле с кодами (только у ролей, у которых код есть) до перевода BFF
    # на роли-данные (R-2), потом будет удалено. Должность — текстом (SPEC-v3 §4.3).
    platform_roles: list[PlatformRoleCode] = Field(default_factory=list)
    platform_role_ids: list[int] = Field(default_factory=list)
    platform_role_refs: list[PlatformRoleRef] = Field(default_factory=list)
    # Итог синхронизации с ERP: `pending` — задача в очереди, `error` — см. `erp_sync_error`,
    # `not_applicable` — доступа к ERP нет.
    erp_sync: ErpSyncStatus = "not_applicable"
    erp_sync_error: str | None = None
    position: str | None = None
    # Язык интерфейса сотрудника (CRM-01b): ru|uz|en, по умолчанию ru.
    language: Language = "ru"


class PlatformRoleGrantRef(PlatformRoleRef):
    """Роль Платформы с матрицей — только в `/me` (R-2, ADR-0012 п. 5).

    BFF Платформы вычисляет по ней разделы сотрудника (объединение ролей) и «вид» по активной роли.
    У системных ролей — матрица каталога. В `/users` матрицы нет: администратор читает их через
    `/api/v1/platform-roles`.
    """

    # Раздел каталога -> `full|read`; скрытые разделы не перечисляются.
    access: dict[str, Literal["full", "read"]]
    # Поля с ограничением, которые роль видит.
    restricted_fields: list[str]


class MeOut(UserOut):
    """Свой профиль + флаги развёртывания, по которым SPA прячет кнопки (истина — на сервере)."""

    platform_role_refs: list[PlatformRoleGrantRef] = Field(default_factory=list)  # type: ignore[assignment]

    # Переход в ERP по SSO включён (PLATFORM_SSO_ENABLED, FIX-03); иначе кнопки «В бэк-офис» нет.
    sso_enabled: bool = False


class MePatch(BaseModel):
    """Своё: режим навигации и подписки на личные уведомления от бота (Q-010)."""

    ui_mode: UiMode | None = None
    notify_system: bool | None = None
    notify_leads: bool | None = None
    language: Language | None = None


class PermissionsResponse(BaseModel):
    roles: list[str]
    permissions: dict[str, dict[str, bool]]


def _unique_platform_roles(value: list[PlatformRoleCode] | None) -> list[PlatformRoleCode] | None:
    if value is None:
        return None
    return cast("list[PlatformRoleCode]", normalize_platform_roles(value))


class UserCreate(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    full_name: str = Field(min_length=1, max_length=255)
    # Нужны роли CRM или роли Платформы; при непустых `platform_roles` роли CRM вычисляются.
    roles: list[Role] | None = Field(default=None, min_length=1)
    platform_roles: list[PlatformRoleCode] | None = None  # старые коды, совместимость до R-2
    platform_role_ids: list[int] | None = None
    position: str | None = Field(default=None, max_length=POSITION_MAX_LEN)

    @field_validator("platform_roles")
    @classmethod
    def _platform_roles_unique(
        cls, value: list[PlatformRoleCode] | None
    ) -> list[PlatformRoleCode] | None:
        return _unique_platform_roles(value)

    @model_validator(mode="after")
    def _has_roles(self) -> "UserCreate":
        if not (self.roles or self.platform_roles or self.platform_role_ids):
            raise ValueError("roles or platform roles are required")
        return self


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

    # Роли Платформы (R-1): полный новый набор id ролей, `[]` — снять все (доступ, выданный ролями,
    # снимается); непустой набор перекрывает `roles`, `platform_access`, `erp_role_codes`.
    # `platform_roles` — старый способ (коды), совместимость BFF до R-2; вместе слать нельзя.
    platform_role_ids: list[int] | None = None
    platform_roles: list[PlatformRoleCode] | None = None
    # Должность (SPEC-v3 §4.3): пустая строка очищает.
    position: str | None = Field(default=None, max_length=POSITION_MAX_LEN)
    language: Language | None = None

    @field_validator("platform_roles")
    @classmethod
    def _platform_roles_unique(
        cls, value: list[PlatformRoleCode] | None
    ) -> list[PlatformRoleCode] | None:
        return _unique_platform_roles(value)


class PasswordReset(BaseModel):
    temporary_password: str


class SsoTokenResponse(BaseModel):
    token: str
    redirect_url: str


class SsoExchangeRequest(BaseModel):
    token: str
