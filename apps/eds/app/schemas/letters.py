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
    IncomingLetterSender,
    JournalEntry,
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


class ReceiptMethod(StrEnum):
    """Способ получения (SPEC-v3 §3.2a п. 1)."""

    POST = "post"
    PAPER = "paper"
    TAXPAYER_CABINET = "taxpayer_cabinet"
    COURIER = "courier"
    EMAIL = "email"


KindCode = Annotated[str, Field(pattern=r"^[a-z][a-z_]{0,31}$")]
RelatedNumber = Annotated[str, Field(min_length=1, max_length=32)]


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
    summary: LongText | None = None  # P8: нет — тема (краткое содержание необязательно)
    sender: IncomingLetterSender
    sender_ref: SenderRef | None = None
    received_at: dt.date
    addressee_crm_user_id: int | None = None
    manager_crm_user_id: int | None = None
    urgent: bool = False
    links: ErpLinksIn | None = None
    file_ids: FileIds = Field(default_factory=list)
    # Карточка делопроизводства (P8, SPEC-v3 §3.2a п. 1)
    kind: KindCode | None = None
    receipt_method: ReceiptMethod | None = None
    signed_by: Annotated[str | None, Field(max_length=255)] = None
    document_due: dt.date | None = None
    related_number: RelatedNumber | None = None  # предыдущий ВХ или наш ИСХ


class RelatedRef(BaseModel):  # eds.yaml LetterRelatedRef
    kind: str  # letter_in | letter_out
    id: uuid.UUID
    number: str


class LetterKindItem(BaseModel):
    code: str
    name: dict[str, str]
    urgent: bool


class LetterKindList(BaseModel):
    items: list[LetterKindItem]


class LetterDuplicate(BaseModel):
    id: uuid.UUID
    number: str
    subject: str
    received_at: dt.date
    status: LetterStatus


class LetterDuplicateList(BaseModel):
    items: list[LetterDuplicate]


class LetterListItem(BaseModel):
    id: uuid.UUID
    number: str
    subject: str
    sender: IncomingLetterSender
    received_at: dt.date
    status: LetterStatus
    links: ErpLinks
    urgent: bool
    due: dt.date | None
    kind: str | None = None


class LetterPage(BaseModel):
    items: list[LetterListItem]
    next_cursor: str | None


class Letter(BaseModel):
    id: uuid.UUID
    number: str
    status: LetterStatus
    subject: str
    summary: str
    sender: IncomingLetterSender
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
    kind: str | None = None
    receipt_method: ReceiptMethod | None = None
    signed_by: str | None = None
    document_due: dt.date | None = None
    related: RelatedRef | None = None
