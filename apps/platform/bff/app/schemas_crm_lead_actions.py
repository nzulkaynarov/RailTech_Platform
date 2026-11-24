"""Модели действий над лидом (LH-1, контракт platform-bff.yaml, теги `messages` и `leads`): закрыть,
передать коллеге, отбросить, открыть заново, «Принято к сведению», отложить, правка контактов.

Тела проверяются как в контракте (`additionalProperties: false`); решения о допустимости действия —
у CRM, BFF переводит словарь (номер лида `L-NNNN`, сотрудник — id строкой, срок отложения — из
имени периода) и ошибки.
"""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas_crm_leads import LEAD_PATTERN

DiscardKind = Literal["spam", "test", "duplicate"]
SnoozePeriod = Literal["hour", "day", "three_days"]


class CloseLeadIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome: Literal["won", "lost"]
    lost_reason: str | None = Field(default=None, max_length=120)
    reason: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def _lost_needs_a_reason(self) -> Self:
        if self.outcome == "lost" and not (self.lost_reason or "").strip():
            raise ValueError("lost_reason is required for an outcome of lost")
        return self


class AssignLeadIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str = Field(pattern=r"^\d{1,12}$")


class DiscardLeadIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: DiscardKind
    duplicate_of: str | None = Field(default=None, pattern=LEAD_PATTERN)

    @model_validator(mode="after")
    def _duplicate_points_to_a_lead(self) -> Self:
        if (self.kind == "duplicate") != (self.duplicate_of is not None):
            raise ValueError("duplicate_of is given for a duplicate and only for it")
        return self


class SnoozeLeadIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    period: SnoozePeriod


class CloseOptions(BaseModel):
    lost_reasons: list[str]
    won_by_erp: bool


class LeadContactsIn(BaseModel):
    """Названные поля меняются, пропущенные не трогаются (`model_fields_set`)."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=40)
    email: str | None = Field(default=None, max_length=255)
    company: str | None = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def _something_to_change(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("name a field to change")
        return self


class LeadDuplicate(BaseModel):
    kind: Literal["lead", "client"]
    lead: str | None
    client_id: int | None
    name: str
    field: Literal["phone", "email"]


class LeadContactsSaved(BaseModel):
    duplicates: list[LeadDuplicate]
