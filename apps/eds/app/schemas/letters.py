"""Схемы входящих писем и резолюций (eds.yaml: Letter, LetterCreate, ResolutionIn, …)."""

import datetime as dt
import uuid
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, Field

from app.schemas.common import (
    ErpLinks,
    ErpLinksIn,
    FileRef,
    JournalEntry,
    LetterSender,
    MarginPct,
    PersonRef,
    SenderRef,
    Strict,
)

Subject = Annotated[str, Field(min_length=1, max_length=300)]
LongText = Annotated[str, Field(min_length=1, max_length=10000)]
Comment = Annotated[str, Field(min_length=1, max_length=4000)]
FileIds = Annotated[list[uuid.UUID], Field(max_length=50)]


class LetterStatus(StrEnum):
    AWAITING_RESOLUTION = "awaiting_resolution"
    RESOLVED = "resolved"
    RETURNED = "returned"
    REJECTED = "rejected"


class Zone(StrEnum):
    GOODS = "goods"
    SERVICES = "services"
    PAYMENT_TERMS = "payment_terms"


class AssigneeIn(Strict):
    crm_user_id: int
    zone: Zone


class Assignee(BaseModel):
    crm_user_id: int
    zone: Zone
    full_name: str


class ResolutionIn(Strict):
    text: Annotated[str, Field(min_length=1, max_length=4000)]
    assignees: Annotated[list[AssigneeIn], Field(min_length=1)]
    due: dt.date
    min_margin_pct: MarginPct | None = None


class Resolution(BaseModel):
    text: str
    assignees: list[Assignee]
    due: dt.date
    min_margin_pct: str | None
    decided_by: PersonRef
    decided_at: dt.datetime


class LetterReturnIn(Strict):
    comment: Comment


class LetterRejectIn(Strict):
    reason: Comment


class LetterSubmitIn(Strict):
    subject: Subject | None = None
    summary: LongText | None = None
    links: ErpLinksIn | None = None
    file_ids: FileIds | None = None
    comment: Annotated[str | None, Field(max_length=4000)] = None


class LetterCreate(Strict):
    subject: Subject
    summary: LongText
    sender: LetterSender
    sender_ref: SenderRef | None = None
    received_at: dt.date
    addressee_crm_user_id: int | None = None
    manager_crm_user_id: int | None = None
    urgent: bool = False
    links: ErpLinksIn | None = None
    file_ids: FileIds = Field(default_factory=list)


class LetterListItem(BaseModel):
    id: uuid.UUID
    number: str
    subject: str
    sender: LetterSender
    received_at: dt.date
    status: LetterStatus
    links: ErpLinks
    urgent: bool
    due: dt.date | None


class LetterPage(BaseModel):
    items: list[LetterListItem]
    next_cursor: str | None


class Letter(BaseModel):
    id: uuid.UUID
    number: str
    status: LetterStatus
    subject: str
    summary: str
    sender: LetterSender
    sender_ref: SenderRef
    received_at: dt.date
    registered_at: dt.datetime
    registered_by: PersonRef | None
    addressee: PersonRef
    manager: PersonRef | None
    urgent: bool
    links: ErpLinks
    files: list[FileRef]
    resolution: Resolution | None
    return_comment: str | None
    reject_reason: str | None
    journal: list[JournalEntry]
