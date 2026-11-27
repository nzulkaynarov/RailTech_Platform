"""Модели запросов и ответов сессии и профиля — схемы `LoginIn`, `Session`, `Me`, `MeUpdate`,
`ChangePasswordIn` из packages/contracts/openapi/platform-bff.yaml."""

from datetime import UTC, datetime
from typing import Annotated, Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, model_serializer, model_validator

from app.rbac import View, modules_for
from app.rbac_generated import ModuleCode, RestrictedField
from app.schemas_profile import avatar_url
from app.session import Language, SessionData, SessionRole

RoleId = Annotated[str, Field(pattern=r"^[1-9][0-9]*$")]

_EMAIL = r"^[^@\s]+@[^@\s]+$"


class LoginIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(max_length=254, pattern=_EMAIL)
    password: str = Field(min_length=1, max_length=256)


class SecondFactorLoginIn(BaseModel):
    """Второй шаг входа (ДВ-4): `challenge` из ответа 202 на `/auth/login` и код."""

    model_config = ConfigDict(extra="forbid")

    challenge: str = Field(min_length=1, max_length=2048)
    code: str = Field(min_length=6, max_length=16)
    remember_device: bool = False


class SecondFactorChallengeOut(BaseModel):
    """202 на `/auth/login`: пароль верен, нужен код второго фактора; сессии ещё нет."""

    second_factor_required: Literal[True] = True
    challenge: str
    # ДВ-4б: фактор обязателен по разделам доступа, но не настроен — `challenge` годится только
    # для `/auth/login/enroll/*` (экран настройки сразу после пароля)
    enrollment_required: bool = False


class EnrollSetupIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    challenge: str = Field(min_length=1, max_length=2048)


class EnrollIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    challenge: str = Field(min_length=1, max_length=2048)
    code: str = Field(min_length=6, max_length=16)


class ChangePasswordIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=8, max_length=256)


class MeUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    language: Language | None = None

    @model_validator(mode="after")
    def _not_empty(self) -> "MeUpdate":
        if not self.model_fields_set:
            raise ValueError("укажите язык")
        if "language" in self.model_fields_set and self.language is None:
            raise ValueError("язык не может быть пустым")
        return self


class AccessFlags(BaseModel):
    crm: bool
    erp: bool


class RoleRef(BaseModel):
    """Роль сотрудника для SPA: id, название из данных, системная ли, код (не у всех)."""

    id: str
    name: str
    system: bool
    code: str | None = None

    @model_serializer(mode="wrap")
    def _omit_empty_code(self, handler: Any) -> dict[str, Any]:
        out: dict[str, Any] = handler(self)
        if out.get("code") is None:
            out.pop("code", None)
        return out

    @classmethod
    def of(cls, role: SessionRole) -> "RoleRef":
        return cls(id=str(role.id), name=role.name, system=role.system, code=role.code)


class Me(BaseModel):
    id: str
    email: str
    name: str
    initials: str = Field(max_length=3)
    position: str | None = None
    avatar_url: str | None = None
    language: Language
    roles: list[RoleRef]
    modules: list[ModuleCode]
    resources: dict[str, Literal["full", "read"]]
    restricted_fields: list[RestrictedField]
    access: AccessFlags
    # Приветствие и тур первого входа показаны (W15-H7): `false` — показать «Добро пожаловать».
    onboarding_done: bool
    # «Что нового» (W-REL): дата записи, о которой окно показано, и последней открытой;
    # None — ничего.
    whats_new_shown: str | None = None
    whats_new_read: str | None = None

    @model_serializer(mode="wrap")
    def _omit_empty_position(self, handler: Any) -> dict[str, Any]:
        out: dict[str, Any] = handler(self)
        for optional in ("position", "avatar_url"):
            if out.get(optional) is None:
                out.pop(optional, None)
        return out


class SessionOut(BaseModel):
    me: Me
    must_change_password: bool
    expires_at: datetime


class EnrolledSession(SessionOut):
    """Сессия после настройки обязательного фактора при входе (ДВ-4б): резервные коды — один раз."""

    backup_codes: list[str]


def initials_of(name: str, email: str) -> str:
    letters = "".join(part[0] for part in name.split()[:2]).upper()
    return (letters or email[:1].upper())[:3]


def build_me(data: SessionData) -> Me:
    """`Me` по снимку профиля: модули, разделы и поля — по объединению делегированного."""
    shown = View.of(data.roles)
    return Me(
        id=str(data.user_id),
        email=data.email,
        name=data.name,
        initials=initials_of(data.name, data.email),
        position=data.position,
        avatar_url=avatar_url(data.user_id, data.avatar_version),
        language=data.language,
        roles=[RoleRef.of(r) for r in data.roles],
        modules=modules_for(shown.access),
        resources=dict(shown.access),
        restricted_fields=cast(list[RestrictedField], list(shown.fields)),
        access=AccessFlags(crm=True, erp="erp" in data.platform_access),
        onboarding_done=data.onboarding_done,
        whats_new_shown=data.whats_new_shown,
        whats_new_read=data.whats_new_read,
    )


def build_session(data: SessionData) -> SessionOut:
    return SessionOut(
        me=build_me(data),
        must_change_password=data.must_change_password,
        expires_at=datetime.fromtimestamp(data.expires_at, UTC),
    )
