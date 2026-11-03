"""Схемы шаблонов резолюций (eds.yaml: ResolutionTemplate, ResolutionTemplateIn; EDS-REG, R2)."""

import uuid
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

from app.schemas.common import PersonRef, Strict
from app.schemas.letters import ResolutionKind


class TemplateScope(StrEnum):
    PERSONAL = "personal"
    COMPANY = "company"


class ResponsibleType(StrEnum):
    PERSON = "person"  # этот сотрудник
    ADDRESSEE = "addressee"  # адресат письма
    NONE = "none"  # выбрать при резолюции


class ResolutionTemplateIn(Strict):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
    scope: TemplateScope
    kind: ResolutionKind
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
    responsible_type: ResponsibleType = ResponsibleType.NONE
    responsible_crm_user_id: int | None = None
    co_executor_ids: Annotated[list[int], Field(max_length=20)] = Field(default_factory=list)
    acquaint_ids: Annotated[list[int], Field(max_length=50)] = Field(default_factory=list)
    due_days: Annotated[int | None, Field(ge=1, le=365)] = None


class ResolutionTemplate(BaseModel):
    id: uuid.UUID
    name: str
    scope: TemplateScope
    kind: ResolutionKind
    text: str
    responsible_type: ResponsibleType
    responsible: PersonRef | None
    co_executors: list[PersonRef]
    acquaint: list[PersonRef]
    due_days: int | None
    owner: PersonRef | None
    editable: bool


class ResolutionTemplateList(BaseModel):
    items: list[ResolutionTemplate]
