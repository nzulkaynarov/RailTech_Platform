"""Схемы делегирования (СОТР-2): каталог действий, наборы по должности, личный набор сотрудника."""

from pydantic import BaseModel, ConfigDict, Field

LabelText = dict[str, str]


class DelegationArea(BaseModel):
    code: str
    label: LabelText


class DelegationAction(BaseModel):
    code: str
    area: str
    label: LabelText


class DelegationPreset(BaseModel):
    """Заготовка «набор по должности» — роль компании и действия, которые она даёт."""

    id: str
    name: str
    codes: list[str]


class DelegationCatalog(BaseModel):
    areas: list[DelegationArea]
    actions: list[DelegationAction]
    presets: list[DelegationPreset]


class EmployeeDelegation(BaseModel):
    """Что делегировано сотруднику сейчас."""

    codes: list[str]
    suggested_preset_id: str | None = None


class EmployeeDelegationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    codes: list[str] = Field(max_length=200)
    # Набор по должности, с которого начали: от него берутся ограничения полей (себестоимость и т.
    # п.)
    preset_id: str | None = Field(default=None, pattern=r"^[1-9][0-9]*$")
    # Лиды в работе у сотрудника, теряющего работу с лидами: кому передать
    # (как у `PATCH /admin/users/{id}`)
    transfer_to_user_id: str | None = Field(default=None, pattern=r"^[1-9][0-9]*$")
