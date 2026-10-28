"""DTO аутентификации, профиля и пользователей (SPEC §10.1)."""

from datetime import date, datetime
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain.erp_roles import ErpRoleCode, normalize_erp_roles
from app.domain.platform_roles import POSITION_MAX_LEN

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
    # и права ERP; пусто — их ведёт админ вручную. Должность — текстом (SPEC-v3 §4.3).
    platform_role_ids: list[int] = Field(default_factory=list)
    platform_role_refs: list[PlatformRoleRef] = Field(default_factory=list)
    # Итог синхронизации с ERP: `pending` — задача в очереди, `error` — см. `erp_sync_error`,
    # `not_applicable` — доступа к ERP нет.
    erp_sync: ErpSyncStatus = "not_applicable"
    erp_sync_error: str | None = None
    position: str | None = None
    # Язык интерфейса сотрудника (CRM-01b): ru|uz|en, по умолчанию ru.
    language: Language = "ru"
    # Профиль, который правит сам сотрудник (W15-H6): телефон, пояс, подпись для писем, ник Telegram
    # (если привязан самим), версия фото (None — фото нет) и замещение на период (включительно).
    phone: str | None = None
    timezone: str = "Asia/Tashkent"
    email_signature: str | None = None
    tg_username: str | None = None
    avatar_version: int | None = None
    deputy_user_id: int | None = None
    deputy_from: date | None = None
    deputy_to: date | None = None
    # Приветствие и тур первого входа уже показаны («Пропустить» / «Больше не показывать», W15-H7).
    onboarding_done: bool = True


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
    # Имя заместителя (W15-H6), чтобы экран не ходил за справочником.
    deputy_name: str | None = None


class MePatch(BaseModel):
    """Своё: режим навигации, подписки на личные уведомления бота (Q-010) и профиль (W15-H6).

    Должность, роли и прочее чужое здесь запрещены (`extra=forbid` -> 422): сотрудник правит только
    свой профиль, должность задаёт админ. Пустая строка в `phone` и `email_signature` очищает поле.
    """

    model_config = ConfigDict(extra="forbid")

    ui_mode: UiMode | None = None
    notify_system: bool | None = None
    notify_leads: bool | None = None
    language: Language | None = None
    full_name: str | None = Field(default=None, min_length=1, max_length=255)
    phone: str | None = Field(default=None, max_length=40)
    timezone: str | None = Field(default=None, max_length=64)
    email_signature: str | None = Field(default=None, max_length=2000)
    # Закрыть приветствие и тур первого входа; снять флаг нельзя, поэтому только `true`.
    onboarding_done: Literal[True] | None = None


class DeputyIn(BaseModel):
    """Замещение на период: `PUT /me/deputy`."""

    deputy_user_id: int = Field(gt=0)
    date_from: date
    date_to: date


class DeputyCandidate(BaseModel):
    id: int
    full_name: str
    position: str | None = None


class TelegramLinkOut(BaseModel):
    """Одноразовая ссылка привязки Telegram: открыть в Telegram или отсканировать QR."""

    url: str
    expires_at: datetime


class CoveredOut(BaseModel):
    """За кого заместитель видит очередь сегодня."""

    user_id: int
    full_name: str
    date_from: date
    date_to: date


class ForgotPasswordRequest(BaseModel):
    identifier: str = Field(min_length=1, max_length=255)


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=20, max_length=128)
    new_password: str = Field(min_length=1, max_length=256)


class PermissionsResponse(BaseModel):
    roles: list[str]
    permissions: dict[str, dict[str, bool]]


class UserCreate(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    full_name: str = Field(min_length=1, max_length=255)
    # Нужны роли CRM или роли Платформы; при непустых `platform_role_ids` роли CRM вычисляются,
    # пустой набор `platform_role_ids` — 422 `roles_required` (R3-D-1).
    roles: list[Role] | None = Field(default=None, min_length=1)
    platform_role_ids: list[int] | None = None
    position: str | None = Field(default=None, max_length=POSITION_MAX_LEN)

    @model_validator(mode="after")
    def _has_roles(self) -> "UserCreate":
        if not (self.roles or self.platform_role_ids):
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

    # Роли Платформы (R-1): полный новый набор id ролей; перекрывает `roles`, `platform_access`,
    # `erp_role_codes`. Пустой набор — 422 `roles_required` (R3-D-1): закрыть доступ — `is_active`.
    platform_role_ids: list[int] | None = Field(
        default=None,
        description=(
            "Полный новый набор ролей Платформы (id). Пустой набор — 422 `roles_required`: "
            "у сотрудника хотя бы одна роль, закрыть доступ — `is_active = false`."
        ),
    )
    # Должность (SPEC-v3 §4.3): пустая строка очищает.
    position: str | None = Field(default=None, max_length=POSITION_MAX_LEN)
    language: Language | None = None


class PasswordReset(BaseModel):
    temporary_password: str


class SsoTokenRequest(BaseModel):
    """Тело выдачи SSO-токена; необязательное: без него (или `aud = erp`) — токен для ERP."""

    aud: Literal["erp", "eds"] = "erp"


class SsoTokenResponse(BaseModel):
    token: str
    redirect_url: str


class SsoExchangeRequest(BaseModel):
    token: str
