"""Модели «Что может человек» (ДОСТ-1): схемы `Capability*` и `EmployeeCapabilities` контракта.

Только чтение: ответ показывает сегодняшние права, ничего не выдаёт. Тексты — на трёх языках
(как в каталоге), язык выбирает экран.
"""

from typing import Literal

from pydantic import BaseModel, Field

from app.schemas import RoleRef
from app.schemas_eds_documents import EdsMoney
from app.schemas_profile import DeputyPeriod
from app.schemas_zones import ZoneText

CapabilityLevel = Literal["none", "view", "work", "decide"]
ActionLevel = Literal["view", "work", "decide"]
ZoneRole = Literal["responsible", "deputy", "curator"]
WarningCode = Literal["only_decider", "nobody_decides", "visa_without_signing"]


class CapabilityText(BaseModel):
    ru: str
    uz: str
    en: str


class CapabilityPerson(BaseModel):
    id: str
    name: str
    initials: str = Field(max_length=3)
    position: str | None = None
    avatar_url: str | None = None


class CapabilityAction(BaseModel):
    key: str
    text: CapabilityText
    on: bool
    # Условия BFF «раздел:уровень» (через «|» — любое из): по ним «Нет доступа» называет возможность
    gates: list[str]


class CapabilityLevelActions(BaseModel):
    level: ActionLevel
    actions: list[CapabilityAction]


class CapabilityRow(BaseModel):
    key: str
    group: str
    name: CapabilityText
    level: CapabilityLevel
    # «Не всё»: часть действий этого и нижних уровней выключена
    partial: bool
    levels: list[CapabilityLevelActions]
    # Роли, из которых строка получена (у каждой роли в отдельности строка не «нет»)
    from_roles: list[RoleRef]
    # Кто ещё держит строку на этом же уровне или выше (карточка человека); не более пяти
    others: list[CapabilityPerson] = []
    others_total: int = Field(default=0, ge=0)


class CapabilityGroup(BaseModel):
    key: str
    step: CapabilityText
    name: CapabilityText
    rows: list[CapabilityRow]


class CapabilitySummary(BaseModel):
    """Итог словами из текстов каталога (без модели): пусто — значит, сказать нечего."""

    does: CapabilityText | None = None
    decides: CapabilityText | None = None
    lacks: CapabilityText | None = None


class CapabilityZone(BaseModel):
    id: str
    code: str
    name: ZoneText
    role: ZoneRole
    valid_to: str | None = None


class CapabilityAuthority(BaseModel):
    id: str
    kinds: list[str]
    limit: EdsMoney | None = None
    basis: Literal["charter", "order", "power_of_attorney"]
    basis_number: str | None = None
    valid_to: str | None = None


class CapabilityWarning(BaseModel):
    code: WarningCode
    capability: str | None = None
    person: CapabilityPerson | None = None
    has_deputy: bool | None = None


class EmployeeCapabilities(BaseModel):
    employee: CapabilityPerson
    roles: list[RoleRef]
    summary: CapabilitySummary
    groups: list[CapabilityGroup]
    # Подпись и зоны читают те, у кого есть на то раздел; «нет данных» — не то же, что «нет подписи»
    signing_known: bool
    signing: list[CapabilityAuthority]
    zones_known: bool
    zones: list[CapabilityZone]
    deputy: DeputyPeriod | None = None
    warnings: list[CapabilityWarning]
    free_for_all: CapabilityText
    # «Нет доступа»: кто выдаёт («Сотрудники и возможности: работать»); нет поля — не известно
    grantors: list[CapabilityPerson] | None = None


class MatrixCell(BaseModel):
    level: CapabilityLevel
    partial: bool


class MatrixCapability(BaseModel):
    key: str
    name: CapabilityText
    levels: list[ActionLevel]


class MatrixGroup(BaseModel):
    key: str
    step: CapabilityText
    name: CapabilityText
    capabilities: list[MatrixCapability]


class MatrixEmployee(BaseModel):
    person: CapabilityPerson
    roles: list[RoleRef]
    cells: dict[str, MatrixCell]
    signing: list[CapabilityAuthority]
    zones: list[CapabilityZone]
    deputy: DeputyPeriod | None = None


class CapabilityMatrix(BaseModel):
    groups: list[MatrixGroup]
    employees: list[MatrixEmployee]
    signing_known: bool
    zones_known: bool
    warnings: list[CapabilityWarning]
    free_for_all: CapabilityText
