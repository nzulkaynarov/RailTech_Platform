"""Модели Admin · Оргструктура и Ролевая матрица — схемы `Employee*` и `Role*` из
packages/contracts/openapi/platform-bff.yaml (0.3.0) и перевод пользователя и роли CRM в них."""

from datetime import datetime
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.rbac_generated import RestrictedField
from app.schemas import AccessFlags, RoleId, RoleRef, initials_of

EmployeeStatus = Literal["active", "invited", "disabled"]
ErpSyncState = Literal["ok", "pending", "error", "not_applicable"]
AccessLevel = Literal["full", "read"]

_EMAIL = r"^[^@\s]+@[^@\s]+$"
_MAX_TEXT = 120
_ERP_SYNC: frozenset[str] = frozenset({"ok", "pending", "error", "not_applicable"})


def _unique(ids: list[str] | None) -> list[str] | None:
    if ids is not None and len(set(ids)) != len(ids):
        raise ValueError("роли не должны повторяться")
    return ids


class Employee(BaseModel):
    id: str
    name: str
    initials: str = Field(max_length=3)
    email: str
    position: str | None = Field(default=None, max_length=_MAX_TEXT)
    roles: list[RoleRef]
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
    role_ids: list[RoleId] = Field(min_length=1)

    @field_validator("role_ids")
    @classmethod
    def _roles_unique(cls, ids: list[str]) -> list[str]:
        return _unique(ids) or ids

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, name: str) -> str:
        if not name.strip():
            raise ValueError("имя не может быть пустым")
        return name.strip()


class EmployeeUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role_ids: list[RoleId] | None = None
    position: str | None = Field(default=None, max_length=_MAX_TEXT)
    is_active: bool | None = None
    transfer_to_user_id: str | None = Field(default=None, pattern=r"^[0-9]+$")

    @field_validator("role_ids")
    @classmethod
    def _roles_unique(cls, ids: list[str] | None) -> list[str] | None:
        return _unique(ids)

    @model_validator(mode="after")
    def _not_empty(self) -> "EmployeeUpdate":
        if not self.model_fields_set:
            raise ValueError("укажите role_ids, position, is_active или transfer_to_user_id")
        for name in ("role_ids", "position", "is_active", "transfer_to_user_id"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} не может быть null")
        return self


def status_of(user: dict[str, Any]) -> EmployeeStatus:
    """Статус по полям CRM: отключён — `is_active = false`; приглашён — пароль ещё временный."""
    if not user.get("is_active", True):
        return "disabled"
    if user.get("must_change_password"):
        return "invited"
    return "active"


def role_refs(user: dict[str, Any]) -> list[RoleRef]:
    """Роли из `platform_role_refs` CRM (названия — данные); битые записи пропускаются."""
    refs: list[RoleRef] = []
    for raw in user.get("platform_role_refs") or []:
        if not isinstance(raw, dict) or not isinstance(raw.get("id"), int):
            continue
        refs.append(
            RoleRef(
                id=str(raw["id"]),
                name=str(raw.get("name") or ""),
                system=bool(raw.get("system")),
                code=raw.get("code") if isinstance(raw.get("code"), str) else None,
            )
        )
    return refs


def to_employee(user: dict[str, Any]) -> Employee:
    """Пользователь CRM -> сотрудник Платформы. Решений здесь нет: только перевод полей.

    `erp_sync` и `erp_sync_error` — итог провижининга ERP из CRM (R-1, Q-PLT-15-1 п. 2).
    """
    name = str(user.get("full_name") or "")
    email = str(user["email"])
    access = {str(a) for a in user.get("platform_access") or ["crm"]}
    erp = "erp" in access
    position = str(user.get("position") or "").strip() or None
    sync = str(user.get("erp_sync") or "")
    error = user.get("erp_sync_error")
    return Employee(
        id=str(user["id"]),
        name=name,
        initials=initials_of(name, email),
        email=email,
        position=position,
        roles=role_refs(user),
        access=AccessFlags(crm="crm" in access, erp=erp),
        status=status_of(user),
        telegram_linked=user.get("tg_user_id") is not None,
        erp_sync=cast(
            ErpSyncState, sync if sync in _ERP_SYNC else ("ok" if erp else "not_applicable")
        ),
        erp_sync_error=str(error) if isinstance(error, str) and error else None,
    )


# --- Admin · Ролевая матрица -------------------------------------------------------------------


class Role(BaseModel):
    id: str
    name: str
    description: str
    system: bool
    code: str | None = None
    # Растёт при каждом изменении; PATCH присылает прочитанную (иначе 409 `role_version_conflict`).
    version: int = Field(ge=1)
    access: dict[str, AccessLevel]
    restricted_fields: list[RestrictedField]
    employees: int = Field(ge=0)
    updated_at: datetime


class RoleList(BaseModel):
    items: list[Role]


class RoleCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=_MAX_TEXT)
    description: str | None = Field(default=None, max_length=1000)
    access: dict[str, AccessLevel]
    restricted_fields: list[RestrictedField]

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, name: str) -> str:
        if not name.strip():
            raise ValueError("название не может быть пустым")
        return name.strip()


class RoleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Версия роли, которую видел клиент (оптимистическая блокировка, 0.3.1).
    version: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=_MAX_TEXT)
    description: str | None = Field(default=None, max_length=1000)
    access: dict[str, AccessLevel] | None = None
    restricted_fields: list[RestrictedField] | None = None

    @model_validator(mode="after")
    def _not_empty(self) -> "RoleUpdate":
        if not self.model_fields_set - {"version"}:
            raise ValueError("укажите name, description, access или restricted_fields")
        for name in self.model_fields_set:
            if getattr(self, name) is None:
                raise ValueError(f"{name} не может быть null")
        if self.name is not None and not self.name.strip():
            raise ValueError("название не может быть пустым")
        return self


class RolePreviewIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role_id: RoleId | None = None
    access: dict[str, AccessLevel] | None = None
    restricted_fields: list[RestrictedField] | None = None


class SectionLevel(BaseModel):
    resource: str
    level: AccessLevel


class PersonRefOut(BaseModel):
    id: str
    name: str
    initials: str = Field(max_length=3)


class RoleImpact(BaseModel):
    employee: PersonRefOut
    gained: list[SectionLevel]
    lost: list[SectionLevel]
    fields_gained: list[RestrictedField]
    fields_lost: list[RestrictedField]


class RolePreview(BaseModel):
    role_id: str | None
    employees_total: int = Field(ge=0)
    employees: list[RoleImpact]
    gained: list[SectionLevel]
    lost: list[SectionLevel]
    fields_gained: list[RestrictedField]
    fields_lost: list[RestrictedField]


def to_role(raw: dict[str, Any]) -> Role:
    """Роль CRM (`/api/v1/platform-roles`) -> роль контракта BFF."""
    return Role(
        id=str(raw["id"]),
        name=str(raw["name"]),
        description=str(raw.get("description") or ""),
        system=bool(raw.get("is_system")),
        code=raw.get("code") or None,
        version=int(raw.get("version") or 1),
        access=dict(raw.get("access") or {}),
        restricted_fields=list(raw.get("restricted_fields") or []),
        employees=int(raw.get("employees") or 0),
        updated_at=raw["updated_at"],
    )


def _levels(rows: Any) -> list[SectionLevel]:
    return [SectionLevel.model_validate(r) for r in rows or []]


def to_preview(raw: dict[str, Any]) -> RolePreview:
    """Предпросмотр CRM -> контракт BFF (сотрудник — `PersonRef`)."""
    impacts = []
    for e in raw.get("employees") or []:
        name = str(e.get("full_name") or "")
        impacts.append(
            RoleImpact(
                employee=PersonRefOut(
                    id=str(e["user_id"]), name=name, initials=initials_of(name, name or "?")
                ),
                gained=_levels(e.get("gained")),
                lost=_levels(e.get("lost")),
                fields_gained=list(e.get("fields_gained") or []),
                fields_lost=list(e.get("fields_lost") or []),
            )
        )
    role_id = raw.get("role_id")
    return RolePreview(
        role_id=str(role_id) if role_id is not None else None,
        employees_total=int(raw.get("employees_total") or 0),
        employees=impacts,
        gained=_levels(raw.get("gained")),
        lost=_levels(raw.get("lost")),
        fields_gained=list(raw.get("fields_gained") or []),
        fields_lost=list(raw.get("fields_lost") or []),
    )
