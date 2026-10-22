"""Модели запросов и ответов сессии и профиля — схемы `LoginIn`, `Session`, `Me`, `MeUpdate`,
`ChangePasswordIn` из packages/contracts/openapi/platform-bff.yaml."""

from datetime import UTC, datetime
from typing import Annotated, Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, model_serializer, model_validator

from app.rbac import View, modules_for, view_roles
from app.rbac_generated import ModuleCode, RestrictedField
from app.session import Language, SessionData, SessionRole

RoleId = Annotated[str, Field(pattern=r"^[0-9]+$")]

_EMAIL = r"^[^@\s]+@[^@\s]+$"


class LoginIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(max_length=254, pattern=_EMAIL)
    password: str = Field(min_length=1, max_length=256)


class ChangePasswordIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=8, max_length=256)


class MeUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    language: Language | None = None
    active_role: RoleId | None = None

    @model_validator(mode="after")
    def _not_empty(self) -> "MeUpdate":
        if not self.model_fields_set:
            raise ValueError("укажите language или active_role")
        if "language" in self.model_fields_set and self.language is None:
            raise ValueError("language не может быть null")
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
    language: Language
    roles: list[RoleRef]
    active_role: str | None
    modules: list[ModuleCode]
    resources: dict[str, Literal["full", "read"]]
    restricted_fields: list[RestrictedField]
    access: AccessFlags

    @model_serializer(mode="wrap")
    def _omit_empty_position(self, handler: Any) -> dict[str, Any]:
        out: dict[str, Any] = handler(self)
        if out.get("position") is None:
            out.pop("position", None)
        return out


class SessionOut(BaseModel):
    me: Me
    must_change_password: bool
    expires_at: datetime


def initials_of(name: str, email: str) -> str:
    letters = "".join(part[0] for part in name.split()[:2]).upper()
    return (letters or email[:1].upper())[:3]


def build_me(data: SessionData) -> Me:
    """`Me` по снимку профиля. Вид (модули, разделы, поля) — по активной роли, если она задана."""
    shown = View.of(view_roles(data.roles, data.active_role))
    active = data.active_role if any(r.id == data.active_role for r in data.roles) else None
    return Me(
        id=str(data.user_id),
        email=data.email,
        name=data.name,
        initials=initials_of(data.name, data.email),
        position=data.position,
        language=data.language,
        roles=[RoleRef.of(r) for r in data.roles],
        active_role=str(active) if active is not None else None,
        modules=modules_for(shown.access),
        resources=dict(shown.access),
        restricted_fields=cast(list[RestrictedField], list(shown.fields)),
        access=AccessFlags(crm=True, erp="erp" in data.platform_access),
    )


def build_session(data: SessionData) -> SessionOut:
    return SessionOut(
        me=build_me(data),
        must_change_password=data.must_change_password,
        expires_at=datetime.fromtimestamp(data.expires_at, UTC),
    )
