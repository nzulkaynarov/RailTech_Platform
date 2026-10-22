"""Ответы /menu-counters, /queue, /queue/cards, /activity/today, /notifications, /search.

Модели повторяют схемы packages/contracts/openapi/platform-bff.yaml; в тестах ответы проверяются
по самому контракту (`ContractChecker`).
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.rbac_generated import ModuleCode, RoleCode

SourceState = Literal["ok", "unavailable", "not_applicable"]
ObjectKind = Literal[
    "lead",
    "client",
    "request",
    "project",
    "letter",
    "quote",
    "contract",
    "invoice",
    "act",
    "memo",
    "chat",
    "ticket",
    "integration",
]
StepCode = Literal[
    "REQUEST", "RESOLUTION", "CALCULATION", "QUOTE", "CONTRACT", "PAYMENT", "DONE", "LOST"
]
QueueItemKind = Literal[
    "answer_lead",
    "take_lead",
    "create_request",
    "service_request",
    "resolve_letter",
    "approve_quote",
    "approve_memo",
    "problem_project",
    "calc_task",
    "supplier_overdue",
    "confirm_payment",
    "issue_invoice",
    "issue_contract",
    "attach_scan",
    "pay_memo",
    "overdue_invoice",
    "ticket",
    "integration_issue",
]
DueLabel = Literal["overdue", "today", "tomorrow", "later", "memo"]
NotificationTab = Literal["all", "decisions", "clients", "system"]


class Sources(BaseModel):
    crm: SourceState
    erp: SourceState


class ObjectRef(BaseModel):
    kind: ObjectKind
    number: str
    title: str | None = None
    path: str
    step: StepCode | None = None


class PersonRef(BaseModel):
    id: str
    name: str
    initials: str = Field(max_length=3)


class MenuCounter(BaseModel):
    module: ModuleCode
    section: str
    count: int = Field(ge=0)
    attention: bool


class MenuCounters(BaseModel):
    items: list[MenuCounter]
    sources: Sources


class QueueItem(BaseModel):
    id: str
    role: RoleCode
    kind: QueueItemKind
    title: str
    subtitle: str
    due_label: DueLabel
    due_at: datetime | None = None
    object: ObjectRef


class Queue(BaseModel):
    items: list[QueueItem]
    sources: Sources


class QueueCard(BaseModel):
    key: str
    label: str
    count: int = Field(ge=0)
    hint: str | None = None
    path: str


class QueueCards(BaseModel):
    cards: list[QueueCard] = Field(max_length=4)
    sources: Sources


class ActivityItem(BaseModel):
    id: str
    actor: PersonRef
    text: str
    module: ModuleCode
    at: datetime
    object: ObjectRef | None = None


class ActivityFeed(BaseModel):
    items: list[ActivityItem]
    sources: Sources


class Notification(BaseModel):
    id: str = Field(pattern=r"^(crm|erp):[0-9]+$")
    tab: NotificationTab
    title: str
    subtitle: str | None = None
    object: ObjectRef | None = None
    created_at: datetime
    read: bool


class NotificationPage(BaseModel):
    items: list[Notification]
    next_cursor: str | None = None
    unread_count: int = Field(ge=0)
    sources: Sources


class SearchHit(BaseModel):
    object: ObjectRef
    title: str
    subtitle: str | None = None


class SearchGroup(BaseModel):
    module: ModuleCode
    items: list[SearchHit] = Field(max_length=10)


class SearchResult(BaseModel):
    groups: list[SearchGroup]
    sources: Sources
