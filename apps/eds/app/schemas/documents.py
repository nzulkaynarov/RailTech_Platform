"""Схемы документов (eds.yaml: Document, DocumentCreate, DocumentSubmitIn, …)."""

import datetime as dt
import uuid
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, PositiveInt, model_validator

from app.schemas.approvals import Decision
from app.schemas.common import FileRef, JournalEntry, LetterSender, Money, PersonRef, Strict
from app.schemas.letters import FileIds, ReplyToLetter, Subject

DocText = Annotated[str, Field(min_length=1, max_length=20000)]
# Почта адресата письма: один адрес без пробелов (формат `email` контракта; доставку проверяет почтовый сервис CRM).
EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


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


class DocumentBody(Strict):
    """Тело документа на бланке (контракт `documents/body.schema.json`); узлы проверяет `rt_docs` в сервисе."""

    version: Literal[1]
    lang: Literal["ru", "uz", "en"]
    page: dict[str, Any] | None = None
    doc: dict[str, Any]

    def raw(self) -> dict[str, Any]:
        return self.model_dump(exclude_none=True)


class OutgoingLetterIn(Strict):
    """Письмо на бланке (P4): тело, «кому», почта адресата, подписант (`null` — подписант бланка)."""

    body: DocumentBody
    recipient_attention: Annotated[str | None, Field(max_length=300)] = None
    recipient_email: Annotated[str | None, Field(max_length=254, pattern=EMAIL_PATTERN)] = None
    signatory_name: Annotated[str | None, Field(max_length=255)] = None
    signatory_position: Annotated[str | None, Field(max_length=255)] = None


class DocumentPdf(BaseModel):
    status: Literal["pending", "ready", "failed"]
    final: bool
    error: str | None
    pages: int | None
    requested_at: dt.datetime
    ready_at: dt.datetime | None


class DocumentMailing(BaseModel):
    id: uuid.UUID
    to: list[str]
    status: Literal["awaiting_pdf", "requested", "sent", "failed"]
    reason: str | None
    requested_by: PersonRef | None
    requested_at: dt.datetime
    finished_at: dt.datetime | None


class RegistrationRequest(BaseModel):
    by: PersonRef
    at: dt.datetime


class OutgoingLetter(BaseModel):
    body: dict[str, Any] | None
    recipient_attention: str | None
    recipient_email: str | None
    signatory_name: str | None
    signatory_position: str | None
    pdf: DocumentPdf | None
    mailings: list[DocumentMailing]
    registration_requested: RegistrationRequest | None


class LetterheadOut(BaseModel):
    configured: bool
    company_name: str | None
    requisites: list[str]
    signatory_name: str | None
    signatory_position: str | None
    has_logo: bool
    updated_at: dt.datetime | None


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
    letter: OutgoingLetterIn | None = None


class DocumentSubmitIn(Strict):
    subject: Subject | None = None
    text: DocText | None = None
    amount: Money | None = None
    due_date: dt.date | None = None
    file_ids: FileIds | None = None
    # Пункт 1.6 плана: согласующие перед шагами шаблона (по порядку) и получатели копии; не передано — прежние.
    approvers: Annotated[list[PositiveInt], Field(max_length=10)] | None = None
    watchers: Annotated[list[PositiveInt], Field(max_length=20)] | None = None
    send: bool = False
    dispatch_method: Literal["email", "paper", "courier", "edo", "other"] | None = "email"

    @model_validator(mode="after")
    def _no_null_text(self) -> "DocumentSubmitIn":
        """`subject` и `text` в eds.yaml — строки без `null`: явный `null` не «пропуск поля», а 422."""
        for name in ("subject", "text"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} must not be null")
        return self


class DocumentSignIn(Strict):
    """Подписание документа уполномоченным лицом (SIGN-3, ADR-0024 п. 1–5)."""

    authority_id: uuid.UUID | None = None
    dispatch_method: Literal["email", "paper", "courier", "edo", "other"] = "email"
    send: bool = True


class DocumentUpdate(DocumentSubmitIn):
    """Правка черновика (или возвращённого документа) без отправки: те же поля, что у `submit`, и связь с проектом."""

    erp_deal_id: int | None = None
    recipient: LetterSender | None = None
    letter: OutgoingLetterIn | None = None


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
    approvers: list[PersonRef] = []
    watchers: list[PersonRef] = []
    amount: Money | None
    due_date: dt.date | None
    files: list[FileRef]
    source_message_id: str | None
    erp_deal_id: int | None
    deal_number: str | None
    recipient: LetterSender | None
    in_reply_to: uuid.UUID | None
    reply_to: ReplyToLetter | None = None
    letter: OutgoingLetter | None
    approval_id: uuid.UUID | None
    payment: DocumentPayment | None
    decisions: list[DocumentDecision]
    journal: list[JournalEntry]
    created_at: dt.datetime
    updated_at: dt.datetime
    archived_at: dt.datetime | None
    signed_at: dt.datetime | None = None
    signed_by: PersonRef | None = None
    signing_authority_id: uuid.UUID | None = None
    signatory_basis: str | None = None
    signatory_basis_text: str | None = None
    acting_for: PersonRef | None = None
    verification_code: str | None = None
    verification_url: str | None = None
    dispatch_method: Literal["email", "paper", "courier", "edo", "other"] | None = None
