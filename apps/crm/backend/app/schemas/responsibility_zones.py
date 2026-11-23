"""DTO реестра зон ответственности (`/api/v1/responsibility-zones`, ЕВ-З)."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

CODE_PATTERN = r"^[a-z][a-z0-9_]{1,39}$"


class LocalizedText(BaseModel):
    ru: str
    uz: str
    en: str


class LocalizedInput(BaseModel):
    ru: str = Field(min_length=1, max_length=120)
    uz: str = Field(min_length=1, max_length=120)
    en: str = Field(min_length=1, max_length=120)


class LocalizedDescription(BaseModel):
    ru: str = Field(default="", max_length=1000)
    uz: str = Field(default="", max_length=1000)
    en: str = Field(default="", max_length=1000)


class ZonePerson(BaseModel):
    id: int
    name: str
    position: str | None
    is_active: bool


class ZoneProblemOut(BaseModel):
    # `no_responsible`, `responsible_inactive`, `deputy_inactive`, `term_expired` — проблемы;
    # `responsible_lacks_permissions` — предупреждение, `sections` — чего не хватает.
    code: str
    severity: Literal["problem", "warning"]
    sections: list[str] = Field(default_factory=list)


class ResponsibilityZoneOut(BaseModel):
    id: int
    code: str
    name: LocalizedText
    description: LocalizedText
    sections: list[str]
    responsible: ZonePerson | None
    deputy: ZonePerson | None
    curator: ZonePerson | None
    basis: str
    valid_from: date | None
    valid_to: date | None
    is_active: bool
    problems: list[ZoneProblemOut]
    updated_at: datetime


class ResponsibilityZoneList(BaseModel):
    items: list[ResponsibilityZoneOut]


class ResponsibilityZoneCreate(BaseModel):
    code: str = Field(pattern=CODE_PATTERN)
    name: LocalizedInput
    description: LocalizedDescription = Field(default_factory=LocalizedDescription)
    # Ключи разделов каталога `platform-rbac.yaml`; неизвестный ключ — 422.
    sections: list[str] = Field(min_length=1, max_length=24)


class ResponsibilityZoneUpdate(BaseModel):
    """Люди, основание и срок: `null` снимает значение, не присланное поле не меняется."""

    responsible_user_id: int | None = None
    deputy_user_id: int | None = None
    curator_user_id: int | None = None
    basis: str | None = Field(default=None, max_length=500)
    valid_from: date | None = None
    valid_to: date | None = None

    @model_validator(mode="after")
    def _term_order(self) -> "ResponsibilityZoneUpdate":
        if self.valid_from and self.valid_to and self.valid_from > self.valid_to:
            raise ValueError("valid_from must not be after valid_to")
        return self
