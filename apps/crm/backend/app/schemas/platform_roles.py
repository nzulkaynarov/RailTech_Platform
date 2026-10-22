"""DTO ролей Платформы (`/api/v1/platform-roles`, ADR-0012, R-1)."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

AccessLevel = Literal["full", "read"]


class PlatformRoleOut(BaseModel):
    id: int
    # `ADMIN`, `DIRECTOR` (системные) и `tpl:MANAGER` и т. п. (из шаблонов); у новых — пусто.
    code: str | None
    name: str
    description: str
    is_system: bool
    # Раздел каталога -> `full|read`; скрытые разделы не хранятся.
    access: dict[str, AccessLevel]
    # Поля с ограничением, которые роль видит (`cost_margin`, `supplier_prices`, `totals_only`).
    restricted_fields: list[str]
    employees: int = Field(description="Сколько сотрудников имеют роль")
    created_by: int | None
    updated_by: int | None
    created_at: datetime
    updated_at: datetime


class PlatformRoleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=1000)
    # Раздел не из каталога или уровень вне `levels` раздела — 422.
    access: dict[str, str] = Field(default_factory=dict)
    restricted_fields: list[str] = Field(default_factory=list)


class PlatformRoleUpdate(BaseModel):
    """Изменение роли; не присланное поле не меняется. Системную роль менять нельзя (409)."""

    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    access: dict[str, str] | None = None
    restricted_fields: list[str] | None = None


class PreviewIn(BaseModel):
    """Черновик роли: с `role_id` — изменение существующей, без него — новая (без последствий)."""

    role_id: int | None = Field(default=None, gt=0)
    access: dict[str, str] | None = None
    restricted_fields: list[str] | None = None


class SectionLevel(BaseModel):
    resource: str
    level: AccessLevel


class EmployeeImpactOut(BaseModel):
    user_id: int
    full_name: str
    is_active: bool
    gained: list[SectionLevel]
    lost: list[SectionLevel]
    fields_gained: list[str]
    fields_lost: list[str]
    erp_gained: list[str]
    erp_lost: list[str]


class PreviewOut(BaseModel):
    """«Что произойдёт»: сотрудники, у которых права изменятся, и общий итог по разделам и полям."""

    role_id: int | None
    employees_total: int
    employees: list[EmployeeImpactOut]
    gained: list[SectionLevel]
    lost: list[SectionLevel]
    fields_gained: list[str]
    fields_lost: list[str]
