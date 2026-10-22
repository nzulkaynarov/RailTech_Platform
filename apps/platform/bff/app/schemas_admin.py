"""Модели Admin · Оргструктура — схемы `Employee`, `EmployeeList`, `EmployeeInvite`,
`EmployeeUpdate` из packages/contracts/openapi/platform-bff.yaml и перевод пользователя CRM
в `Employee`."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.rbac import known_roles
from app.rbac_generated import RoleCode
from app.schemas import AccessFlags, initials_of

EmployeeStatus = Literal["active", "invited", "disabled"]
ErpSyncState = Literal["ok", "pending", "error", "not_applicable"]

_EMAIL = r"^[^@\s]+@[^@\s]+$"
_MAX_TEXT = 120


def _unique(roles: list[RoleCode] | None) -> list[RoleCode] | None:
    if roles is not None and len(set(roles)) != len(roles):
        raise ValueError("роли не должны повторяться")
    return roles


class Employee(BaseModel):
    id: str
    name: str
    initials: str = Field(max_length=3)
    email: str
    position: str | None = Field(default=None, max_length=_MAX_TEXT)
    roles: list[RoleCode]
    access: AccessFlags
    status: EmployeeStatus
    telegram_linked: bool
    erp_sync: ErpSyncState
    erp_sync_error: str | None = None


class EmployeeList(BaseModel):
    items: list[Employee]


class EmployeeInvite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(max_length=254, pattern=_EMAIL)
    name: str = Field(min_length=1, max_length=_MAX_TEXT)
    position: str | None = Field(default=None, max_length=_MAX_TEXT)
    roles: list[RoleCode] = Field(min_length=1)

    @field_validator("roles")
    @classmethod
    def _roles_unique(cls, roles: list[RoleCode]) -> list[RoleCode]:
        return _unique(roles) or roles

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, name: str) -> str:
        if not name.strip():
            raise ValueError("имя не может быть пустым")
        return name.strip()


class EmployeeUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    roles: list[RoleCode] | None = None
    position: str | None = Field(default=None, max_length=_MAX_TEXT)
    is_active: bool | None = None

    @field_validator("roles")
    @classmethod
    def _roles_unique(cls, roles: list[RoleCode] | None) -> list[RoleCode] | None:
        return _unique(roles)

    @model_validator(mode="after")
    def _not_empty(self) -> "EmployeeUpdate":
        if not self.model_fields_set:
            raise ValueError("укажите roles, position или is_active")
        if "roles" in self.model_fields_set and self.roles is None:
            raise ValueError("roles не может быть null")
        if "position" in self.model_fields_set and self.position is None:
            raise ValueError("position не может быть null; пустая строка очищает должность")
        if "is_active" in self.model_fields_set and self.is_active is None:
            raise ValueError("is_active не может быть null")
        return self


def status_of(user: dict[str, Any]) -> EmployeeStatus:
    """Статус по полям CRM: отключён — `is_active = false`; приглашён — пароль ещё временный."""
    if not user.get("is_active", True):
        return "disabled"
    if user.get("must_change_password"):
        return "invited"
    return "active"


def to_employee(user: dict[str, Any]) -> Employee:
    """Пользователь CRM -> сотрудник Платформы. Решений здесь нет: только перевод полей.

    `erp_sync`: CRM не отдаёт итог провижининга (`users.erp_sync_error` виден только центру
    внешних сервисов), поэтому без доступа к ERP это `not_applicable`, с доступом — `ok`;
    `pending` и `error` появятся, когда CRM отдаст поле (Q-PLT-15-2).
    """
    name = str(user.get("full_name") or "")
    email = str(user["email"])
    access = {str(a) for a in user.get("platform_access") or ["crm"]}
    erp = "erp" in access
    position = str(user.get("position") or "").strip() or None
    return Employee(
        id=str(user["id"]),
        name=name,
        initials=initials_of(name, email),
        email=email,
        position=position,
        roles=known_roles(user.get("platform_roles") or []),
        access=AccessFlags(crm="crm" in access, erp=erp),
        status=status_of(user),
        telegram_linked=user.get("tg_user_id") is not None,
        erp_sync="ok" if erp else "not_applicable",
    )
