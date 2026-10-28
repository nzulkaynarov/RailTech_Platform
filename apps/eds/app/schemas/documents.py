"""Схемы документов (eds.yaml: Document, DocumentCreate, DocumentSubmitIn, …)."""

import datetime as dt
import uuid
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, Field, model_validator

from app.schemas.approvals import Decision
from app.schemas.common import FileRef, JournalEntry, LetterSender, Money, PersonRef, Strict
from app.schemas.letters import FileIds, Subject

DocText = Annotated[str, Field(min_length=1, max_length=20000)]


class DocumentKind(StrEnum):
    MEMO = "memo"
    APPLICATION = "application"
    REPORT = "report"
    LETTER_OUT = "letter_out"


class DocumentStatus(StrEnum):
    DRAFT = "draft"
    ON_APPROVAL = "on_approval"
    RETURNED = "returned"
    REJECTED = "rejected"
    APPROVED = "approved"
    TO_ACCOUNTANT = "to_accountant"
    PAID = "paid"
    SENT = "sent"


class DocumentCreate(Strict):
    kind: DocumentKind
    subject: Subject
    text: DocText
    addressee_crm_user_id: int | None = None
    amount: Money | None = None
    due_date: dt.date | None = None
    file_ids: FileIds = Field(default_factory=list)
    source_message_id: Annotated[str | None, Field(max_length=128)] = None
    erp_deal_id: int | None = None
    recipient: LetterSender | None = None
    in_reply_to: uuid.UUID | None = None


class DocumentSubmitIn(Strict):
    subject: Subject | None = None
    text: DocText | None = None
    amount: Money | None = None
    due_date: dt.date | None = None
    file_ids: FileIds | None = None

    @model_validator(mode="after")
    def _no_null_text(self) -> "DocumentSubmitIn":
        """`subject` и `text` в eds.yaml — строки без `null`: явный `null` не «пропуск поля», а 422."""
        for name in ("subject", "text"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} must not be null")
        return self


class DocumentUpdate(DocumentSubmitIn):
    """Правка черновика (или возвращённого документа) без отправки: те же поля, что у `submit`, и связь с проектом."""

    erp_deal_id: int | None = None
    recipient: LetterSender | None = None


class DocumentPaymentIn(Strict):
    """«Оплачено» (SPEC-v3 §3.2 п. 5): дата и сумма платежа, платёжка бухгалтера (файл, загруженный `POST /files`)."""

    paid_on: dt.date
    amount: Money
    receipt_file_id: uuid.UUID | None = None
    note: Annotated[str | None, Field(max_length=500)] = None


class DocumentPayment(BaseModel):
    """Факт оплаты служебной записки: кто, когда, сколько, какой платёжкой."""

    paid_on: dt.date
    amount: Money
    receipt_file_id: uuid.UUID | None
    note: str | None
    paid_by: PersonRef
    recorded_at: dt.datetime


class DocumentDecision(BaseModel):
    round: int
    step: int
    decision: Decision
    comment: str | None
    by: PersonRef
    at: dt.datetime


class DocumentListItem(BaseModel):
    id: uuid.UUID
    kind: DocumentKind
    number: str | None
    status: DocumentStatus
    subject: str
    author: PersonRef
    amount: Money | None
    due_date: dt.date | None
    files_count: int
    paid_on: dt.date | None
    created_at: dt.datetime


class DocumentPage(BaseModel):
    items: list[DocumentListItem]
    next_cursor: str | None


class Document(BaseModel):
    id: uuid.UUID
    kind: DocumentKind
    number: str | None
    status: DocumentStatus
    version: int
    subject: str
    text: str
    author: PersonRef
    addressee: PersonRef | None
    amount: Money | None
    due_date: dt.date | None
    files: list[FileRef]
    source_message_id: str | None
    erp_deal_id: int | None
    deal_number: str | None
    recipient: LetterSender | None
    in_reply_to: uuid.UUID | None
    approval_id: uuid.UUID | None
    payment: DocumentPayment | None
    decisions: list[DocumentDecision]
    journal: list[JournalEntry]
    created_at: dt.datetime
    updated_at: dt.datetime
    archived_at: dt.datetime | None
