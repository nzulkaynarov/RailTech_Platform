"""Схемы входящей почты общего ящика (W18A-P2, B-INB-5; контракт: tag `inbound-mail`, 0.34.0;
папки «Спам» и загрузка писем за период — W18A-P2-2, 0.35.0)."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from app.clients import crm_models as crm
from app.feeds.numbers import lead_number, letter_ref

MailStatus = Literal["new", "spam", "registered", "lead", "archived"]


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ImapFolder(_Out):
    name: str
    label: str
    spam: bool


class ImapHistory(_Out):
    id: int
    days: int
    status: Literal["running", "done", "error"]
    found: int
    processed: int
    created: int
    limited: bool
    error_kind: str | None
    started_at: datetime
    finished_at: datetime | None


class ImapServerFolder(_Out):
    name: str
    label: str
    junk: bool
    selectable: bool


class ImapFolders(_Out):
    ok: bool
    error_kind: str | None
    detail: str | None
    folders: list[ImapServerFolder]
    spam_suggestion: str | None


class ImapFolderIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    spam: bool = False


class ImapHistoryIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    days: Literal[7, 14, 30, 90]


class ImapConnector(_Out):
    configured: bool
    host: str
    port: int
    security: Literal["ssl", "starttls"]
    mailbox: str
    assist_enabled: bool
    username: str
    password_configured: bool
    password_last4: str | None
    password_updated_at: datetime | None
    secrets_enabled: bool
    last_poll_at: datetime | None
    last_ok_at: datetime | None
    last_error_kind: str | None
    last_error: str | None
    folders: list[ImapFolder]
    history: ImapHistory | None


class ImapSettingsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    host: str = Field(max_length=253)
    port: int = Field(default=993, ge=1, le=65535)
    security: Literal["ssl", "starttls"] = "ssl"
    mailbox: str = Field(default="INBOX", min_length=1, max_length=200)
    folders: list[ImapFolderIn] | None = Field(default=None, max_length=10)
    assist_enabled: bool = True
    username: str | None = Field(default=None, max_length=255)
    imap_password: SecretStr | None = Field(default=None, min_length=1, max_length=512)
    password: SecretStr = Field(min_length=1, max_length=256)


class ImapCheck(_Out):
    ok: bool
    error_kind: str | None
    detail: str | None
    messages: int | None
    latency_ms: int | None


class InboundMailAssist(_Out):
    status: Literal["none", "done", "unavailable", "off"]
    kind: Literal["buyer", "official", "supplier_doc", "other"] | None
    summary: str | None
    action: Literal["register", "lead", "archive"] | None


class InboundMailLink(_Out):
    id: int
    number: str
    name: str


class InboundMailItem(_Out):
    id: int
    status: MailStatus
    from_email: str
    from_name: str
    subject: str
    received_at: datetime
    sent_at: datetime | None
    preview: str
    attachments_count: int
    assist: InboundMailAssist
    client: InboundMailLink | None
    lead: InboundMailLink | None
    from_history: bool


class InboundMailMailbox(_Out):
    configured: bool
    last_poll_at: datetime | None
    last_ok_at: datetime | None
    last_error_kind: str | None


class InboundMailCounts(_Out):
    new: int
    history: int
    spam: int


class InboundMailPage(_Out):
    items: list[InboundMailItem]
    total: int
    mailbox: InboundMailMailbox
    counts: InboundMailCounts


class InboundMailAttachment(_Out):
    index: int
    name: str
    content_type: str
    size: int


class InboundMailSkipped(_Out):
    name: str
    reason: Literal["type", "size", "count"]


class InboundMailReply(_Out):
    id: int
    to_email: str
    subject: str
    status: str
    created_at: datetime
    sent_at: datetime | None


class InboundMail(InboundMailItem):
    to: list[str]
    text: str
    attachments: list[InboundMailAttachment]
    skipped: list[InboundMailSkipped]
    too_large: bool
    inns: list[str]
    letter_number: str | None
    letter_ref: str | None
    result_lead: InboundMailLink | None
    archive_reason: str | None
    handled_at: datetime | None
    replies: list[InboundMailReply]


class InboundMailLeadResult(_Out):
    lead_id: int
    lead_number: str
    created: bool


class InboundMailArchiveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=3, max_length=500)


class InboundMailReplyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=20000)


def _lead(link: crm.InboundMailLink | None) -> InboundMailLink | None:
    if link is None:
        return None
    return InboundMailLink(id=link.id, number=lead_number(link.id), name=link.name)


def _client(link: crm.InboundMailLink | None) -> InboundMailLink | None:
    return InboundMailLink(id=link.id, number=str(link.id), name=link.name) if link else None


def _assist(src: crm.InboundMailAssist) -> InboundMailAssist:
    return InboundMailAssist.model_validate(src.model_dump(mode="json"))


def to_item(src: crm.InboundMailItem | crm.InboundMailOut) -> InboundMailItem:
    return InboundMailItem(
        id=src.id,
        status=src.status,
        from_email=src.from_email,
        from_name=src.from_name,
        subject=src.subject,
        received_at=src.received_at,
        sent_at=src.sent_at,
        preview=src.preview,
        attachments_count=src.attachments_count,
        assist=_assist(src.assist),
        client=_client(src.client),
        lead=_lead(src.lead),
        from_history=bool(src.from_history),
    )


def to_page(src: crm.InboundMailPage) -> InboundMailPage:
    return InboundMailPage(
        items=[to_item(i) for i in src.items],
        total=src.total,
        mailbox=InboundMailMailbox.model_validate(src.mailbox.model_dump(mode="json")),
        counts=InboundMailCounts.model_validate(src.counts.model_dump(mode="json")),
    )


def to_mail(src: crm.InboundMailOut) -> InboundMail:
    number = src.eds_letter_number
    return InboundMail(
        **to_item(src).model_dump(),
        to=list(src.to),
        text=src.text,
        attachments=[InboundMailAttachment.model_validate(a.model_dump()) for a in src.attachments],
        skipped=[InboundMailSkipped.model_validate(s.model_dump()) for s in src.skipped],
        too_large=src.too_large,
        inns=list(src.inns),
        letter_number=number,
        letter_ref=letter_ref(number, src.subject).path if number else None,
        result_lead=_lead(src.result_lead),
        archive_reason=src.archive_reason,
        handled_at=src.handled_at,
        replies=[InboundMailReply.model_validate(r.model_dump()) for r in src.replies],
    )


def to_history(src: crm.ImapHistoryOut) -> ImapHistory:
    return ImapHistory.model_validate(src.model_dump(mode="json"))


def to_connector(src: crm.ImapStatusOut) -> "ImapConnector":
    data = src.model_dump(exclude={"folders", "history"})
    return ImapConnector(
        **data,
        folders=[
            ImapFolder(name=f.name, label=f.label, spam=bool(f.spam)) for f in src.folders or []
        ],
        history=to_history(src.history) if src.history is not None else None,
    )


def to_folders(src: crm.ImapFoldersOut) -> ImapFolders:
    return ImapFolders(
        ok=src.ok,
        error_kind=src.error_kind,
        detail=src.detail,
        folders=[ImapServerFolder.model_validate(f.model_dump()) for f in src.folders or []],
        spam_suggestion=src.spam_suggestion,
    )
