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
    # Путь делопроизводства (P8b, SPEC-v3 §3.2a)
    IN_EXECUTION = "in_execution"
    EXECUTED = "executed"
    NOTED = "noted"


class LetterTrack(StrEnum):
    """Путь резолюции: `calc` — письмо по заявке клиента (расчёт по зонам), `office` — делопроизводство (P8b)."""

    CALC = "calc"
    OFFICE = "office"


class ResolutionKind(StrEnum):
    EXECUTE = "execute"  # К исполнению
    REPLY = "reply"  # Подготовить ответ
    INFO = "info"  # Для сведения


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
    resolution_draft: "ResolutionDraftIn | None" = None  # проект резолюции делопроизводителя (P8b)


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
    track: LetterTrack = LetterTrack.OFFICE
    on_control: bool = False
    overdue: bool = False
    executor: PersonRef | None = None


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
    track: LetterTrack = LetterTrack.OFFICE
    on_control: bool = False
    suggested_due: dt.date | None = None
    resolution_draft: "ResolutionDraft | None" = None
    office_resolution: "OfficeResolution | None" = None
    instructions: "list[InstructionOut]" = Field(default_factory=list)
    acquaintances: "list[AcquaintanceOut]" = Field(default_factory=list)
    executed_at: dt.datetime | None = None


# --- Путь делопроизводства: резолюция трёх типов, поручения, переносы, ознакомление (P8b, SPEC-v3 §3.2a) ---------

PeopleIds = Annotated[list[int], Field(max_length=20)]
AcquaintIds = Annotated[list[int], Field(max_length=50)]
ResolutionText = Annotated[str, Field(min_length=1, max_length=4000)]


class ResolutionDraftIn(Strict):
    kind: ResolutionKind | None = None
    responsible_crm_user_id: int | None = None
    due: dt.date | None = None
    text: Annotated[str | None, Field(max_length=4000)] = None
    co_executor_ids: PeopleIds = Field(default_factory=list)
    acquaint_ids: AcquaintIds = Field(default_factory=list)


class ResolutionDraft(BaseModel):
    kind: ResolutionKind | None
    responsible: PersonRef | None
    due: dt.date | None
    text: str | None
    co_executors: list[PersonRef]
    acquaint: list[PersonRef]
    drafted_by: PersonRef
    drafted_at: dt.datetime


class OfficeResolutionIn(Strict):
    kind: ResolutionKind
    responsible_crm_user_id: int | None = None
    due: dt.date | None = None
    text: ResolutionText
    co_executor_ids: PeopleIds = Field(default_factory=list)
    acquaint_ids: AcquaintIds = Field(default_factory=list)


class OfficeResolution(BaseModel):
    kind: ResolutionKind
    text: str
    due: dt.date | None
    responsible: PersonRef | None
    co_executors: list[PersonRef]
    acquaint: list[PersonRef]
    decided_by: PersonRef
    decided_at: dt.datetime


class InstructionStatus(StrEnum):
    IN_WORK = "in_work"
    EXECUTED = "executed"


class InstructionRole(StrEnum):
    RESPONSIBLE = "responsible"
    CO_EXECUTOR = "co_executor"


class ExtensionStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class OutgoingRef(BaseModel):
    id: uuid.UUID
    number: str


class InstructionExtensionOut(BaseModel):
    id: uuid.UUID
    old_due: dt.date
    new_due: dt.date
    reason: str
    status: ExtensionStatus
    requested_by: PersonRef
    requested_at: dt.datetime
    decided_by: PersonRef | None
    decided_at: dt.datetime | None
    comment: str | None


class InstructionOut(BaseModel):
    id: uuid.UUID
    kind: ResolutionKind
    role: InstructionRole
    person: PersonRef
    due: dt.date
    text: str
    status: InstructionStatus
    overdue: bool
    report: str | None
    files: list[FileRef]
    outgoing: OutgoingRef | None
    executed_at: dt.datetime | None
    extensions: list[InstructionExtensionOut]


class AcquaintanceOut(BaseModel):
    person: PersonRef
    acknowledged_at: dt.datetime | None


class InstructionCompleteIn(Strict):
    report: Annotated[str | None, Field(max_length=10000)] = None
    file_ids: Annotated[list[uuid.UUID], Field(max_length=20)] = Field(default_factory=list)
    outgoing_number: Annotated[str | None, Field(min_length=1, max_length=32)] = None


class ExtensionRequestIn(Strict):
    new_due: dt.date
    reason: Annotated[str, Field(min_length=1, max_length=2000)]


class ExtensionDecision(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"


class ExtensionDecisionIn(Strict):
    decision: ExtensionDecision
    comment: Annotated[str | None, Field(max_length=2000)] = None


class LetterTaskLetter(BaseModel):
    id: uuid.UUID
    number: str
    subject: str
    sender_name: str | None
    urgent: bool


class InstructionTask(BaseModel):
    id: uuid.UUID
    letter: LetterTaskLetter
    kind: ResolutionKind
    role: InstructionRole
    due: dt.date
    overdue: bool
    extension_pending: bool
    created_at: dt.datetime


class ExtensionTask(BaseModel):
    id: uuid.UUID
    instruction_id: uuid.UUID
    letter: LetterTaskLetter
    executor: PersonRef
    old_due: dt.date
    new_due: dt.date
    reason: str
    requested_at: dt.datetime


class AcquaintanceTask(BaseModel):
    letter: LetterTaskLetter
    created_at: dt.datetime


class LetterTasks(BaseModel):
    instructions: list[InstructionTask]
    extensions: list[ExtensionTask]
    acquaintances: list[AcquaintanceTask]


class EmployeeChoice(BaseModel):
    crm_user_id: int
    full_name: str
    position: str | None


class EmployeeList(BaseModel):
    items: list[EmployeeChoice]


LetterCreate.model_rebuild()
Letter.model_rebuild()
