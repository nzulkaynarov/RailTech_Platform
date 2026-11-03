"""Шаблоны резолюций (контракт BFF: `/eds/resolution-templates`, EDS-REG, R2).

Ids сотрудников — строки, люди — `PersonRef` Платформы; правила (кто видит и меняет, «Для сведения»,
активные сотрудники) — в EDS."""

import uuid
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.feeds.models import PersonRef
from app.schemas import initials_of

Scope = Literal["personal", "company"]
ResponsibleType = Literal["person", "addressee", "none"]
Kind = Literal["execute", "reply", "info"]
UserId = Annotated[str, StringConstraints(pattern=r"^[1-9][0-9]*$")]


class ResolutionTemplateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
    scope: Scope
    kind: Kind
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
    responsible_type: ResponsibleType = "none"
    responsible_id: UserId | None = None
    co_executor_ids: Annotated[list[UserId], Field(max_length=20)] = Field(default_factory=list)
    acquaint_ids: Annotated[list[UserId], Field(max_length=50)] = Field(default_factory=list)
    due_days: Annotated[int | None, Field(ge=1, le=365)] = None

    def for_eds(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "scope": self.scope,
            "kind": self.kind,
            "text": self.text,
            "responsible_type": self.responsible_type,
            "responsible_crm_user_id": int(self.responsible_id) if self.responsible_id else None,
            "co_executor_ids": [int(i) for i in dict.fromkeys(self.co_executor_ids)],
            "acquaint_ids": [int(i) for i in dict.fromkeys(self.acquaint_ids)],
            "due_days": self.due_days,
        }


class _EdsPerson(BaseModel):
    crm_user_id: int
    full_name: str


class _EdsTemplate(BaseModel):
    id: uuid.UUID
    name: str
    scope: Scope
    kind: Kind
    text: str
    responsible_type: ResponsibleType
    responsible: _EdsPerson | None
    co_executors: list[_EdsPerson]
    acquaint: list[_EdsPerson]
    due_days: int | None
    owner: _EdsPerson | None
    editable: bool


class ResolutionTemplate(BaseModel):
    id: uuid.UUID
    name: str
    scope: Scope
    kind: Kind
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


def _person(p: _EdsPerson) -> PersonRef:
    return PersonRef(id=str(p.crm_user_id), name=p.full_name, initials=initials_of(p.full_name, ""))


def to_template(raw: Any) -> ResolutionTemplate:
    """Шаблон EDS → шаблон Платформы (неверная форма — `ValidationError`, ответ 503)."""
    t = _EdsTemplate.model_validate(raw)
    return ResolutionTemplate(
        id=t.id,
        name=t.name,
        scope=t.scope,
        kind=t.kind,
        text=t.text,
        responsible_type=t.responsible_type,
        responsible=_person(t.responsible) if t.responsible else None,
        co_executors=[_person(p) for p in t.co_executors],
        acquaint=[_person(p) for p in t.acquaint],
        due_days=t.due_days,
        owner=_person(t.owner) if t.owner else None,
        editable=t.editable,
    )
