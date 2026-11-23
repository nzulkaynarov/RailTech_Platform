"""Модели Admin · Зоны ответственности — схемы `Zone*` из `platform-bff.yaml` контракта
и перевод зоны CRM (`/api/v1/responsibility-zones`) в них (ЕВ-З)."""

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.rbac_generated import RESOURCE_MODULE

ZoneProblemCode = Literal[
    "no_responsible",
    "responsible_lacks_permissions",
    "responsible_inactive",
    "deputy_inactive",
    "term_expired",
]
ZoneProblemSeverity = Literal["problem", "warning"]
ZONE_ID = r"^[1-9][0-9]*$"
ZONE_CODE = r"^[a-z][a-z0-9_]{1,39}$"
_SECTIONS_MAX = 24


class ZoneText(BaseModel):
    ru: str
    uz: str
    en: str


class ZoneTextIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ru: str = Field(min_length=1, max_length=120)
    uz: str = Field(min_length=1, max_length=120)
    en: str = Field(min_length=1, max_length=120)


class ZoneDescriptionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ru: str = Field(default="", max_length=1000)
    uz: str = Field(default="", max_length=1000)
    en: str = Field(default="", max_length=1000)


class ZonePerson(BaseModel):
    id: str
    name: str
    position: str | None = None
    active: bool


class ZoneProblem(BaseModel):
    code: ZoneProblemCode
    severity: ZoneProblemSeverity
    sections: list[str] | None = None


class Zone(BaseModel):
    id: str
    code: str
    name: ZoneText
    description: ZoneText
    sections: list[str]
    responsible: ZonePerson | None = None
    deputy: ZonePerson | None = None
    curator: ZonePerson | None = None
    basis: str
    valid_from: date | None = None
    valid_to: date | None = None
    active: bool
    problems: list[ZoneProblem]
    updated_at: datetime


class ZoneList(BaseModel):
    items: list[Zone]


class ZoneSummary(BaseModel):
    zones_total: int = Field(ge=0)
    without_responsible: int = Field(ge=0)
    with_problems: int = Field(ge=0)


class ZoneCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(pattern=ZONE_CODE)
    name: ZoneTextIn
    description: ZoneDescriptionIn | None = None
    sections: list[str] = Field(min_length=1, max_length=_SECTIONS_MAX)

    @model_validator(mode="after")
    def _sections_known(self) -> "ZoneCreate":
        unknown = [s for s in self.sections if s not in RESOURCE_MODULE]
        if unknown or len(set(self.sections)) != len(self.sections):
            raise ValueError("разделы должны быть из каталога и без повторов")
        return self


class ZoneUpdate(BaseModel):
    """Люди, основание и срок; `null` снимает значение, не присланное поле не меняется."""

    model_config = ConfigDict(extra="forbid")

    responsible_id: str | None = Field(default=None, pattern=ZONE_ID)
    deputy_id: str | None = Field(default=None, pattern=ZONE_ID)
    curator_id: str | None = Field(default=None, pattern=ZONE_ID)
    basis: str | None = Field(default=None, max_length=500)
    valid_from: date | None = None
    valid_to: date | None = None

    @model_validator(mode="after")
    def _term_order(self) -> "ZoneUpdate":
        if self.valid_from and self.valid_to and self.valid_from > self.valid_to:
            raise ValueError("начало срока позже его конца")
        return self


def _person(raw: Any) -> ZonePerson | None:
    if not isinstance(raw, dict):
        return None
    return ZonePerson(
        id=str(raw["id"]),
        name=str(raw["name"]),
        position=raw.get("position") or None,
        active=bool(raw.get("is_active")),
    )


def to_zone(raw: dict[str, Any]) -> Zone:
    """Зона CRM -> зона контракта BFF (id сотрудников — строки)."""
    return Zone(
        id=str(raw["id"]),
        code=str(raw["code"]),
        name=ZoneText.model_validate(raw["name"]),
        description=ZoneText.model_validate(raw["description"]),
        sections=list(raw.get("sections") or []),
        responsible=_person(raw.get("responsible")),
        deputy=_person(raw.get("deputy")),
        curator=_person(raw.get("curator")),
        basis=str(raw.get("basis") or ""),
        valid_from=raw.get("valid_from"),
        valid_to=raw.get("valid_to"),
        active=bool(raw.get("is_active")),
        problems=[
            ZoneProblem(
                code=p["code"],
                severity=p["severity"],
                sections=list(p.get("sections") or []) or None,
            )
            for p in raw.get("problems") or []
        ],
        updated_at=raw["updated_at"],
    )
