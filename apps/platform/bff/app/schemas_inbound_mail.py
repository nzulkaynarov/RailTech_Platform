"""Схемы входящей почты общего ящика (W18A-P2, B-INB-5; контракт: tag `inbound-mail`, 0.34.0;
папки «Спам» и загрузка писем за период — W18A-P2-2, 0.35.0; обращение — статусы, «в работе»,
цепочки, адресаты — W18A-P2-3, 0.36.0; показ письма: безопасный HTML, текст без цитаты — P2-4)."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from app.clients import crm_models as crm
from app.feeds.numbers import lead_number, letter_ref

MailStatus = Literal["new", "in_work", "registering", "done", "spam"]
MailOutcome = Literal["registered", "lead", "replied", "archived"]
MailView = Literal["new", "mine", "in_work", "done", "spam", "all"]


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
    personal_rule: bool
    personal_label: str
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
    personal_rule: bool = True
    personal_label: str = Field(default="Адресовано лично", min_length=1, max_length=80)
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


class InboundMailPerson(_Out):
    id: int
    name: str


class InboundMailResult(_Out):
    outcome: MailOutcome | None
    by: InboundMailPerson | None
    at: datetime | None
    letter_number: str | None
    letter_ref: str | None
    lead: InboundMailLink | None
    reason: str | None


class InboundMailItem(_Out):
    id: int
    status: MailStatus
    from_email: str
    from_name: str
    subject: str
    received_at: datetime
    sent_at: datetime | None
    activity_at: datetime
    preview: str
    attachments_count: int
    assist: InboundMailAssist
    client: InboundMailLink | None
    lead: InboundMailLink | None
    from_history: bool
    assignee: InboundMailPerson | None
    assigned_at: datetime | None
    personal: bool
    thread_reply: bool
    unread: bool
    messages_count: int
    eds_waiting: bool
    result: InboundMailResult | None


class InboundMailMailbox(_Out):
    configured: bool
    last_poll_at: datetime | None
    last_ok_at: datetime | None
    last_error_kind: str | None
    personal_label: str


class InboundMailCounts(_Out):
    new: int
    history: int
    mine: int
    in_work: int
    done: int
    spam: int
    all: int
    unread_new: int


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
    inline: bool


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
    by: InboundMailPerson | None


class InboundMailAddress(_Out):
    email: str
    staff: InboundMailPerson | None
    mailbox: bool


class InboundMailMessage(_Out):
    id: int
    from_email: str
    from_name: str
    at: datetime
    text: str
    text_tail: str
    html: str | None
    html_remote_images: int
    attachments: list[InboundMailAttachment]
    new_participant: bool


class InboundMailEvent(_Out):
    at: datetime
    action: str
    actor: InboundMailPerson | None
    detail: str | None


class InboundMail(InboundMailItem):
    to: list[InboundMailAddress]
    cc: list[InboundMailAddress]
    text: str
    attachments: list[InboundMailAttachment]
    skipped: list[InboundMailSkipped]
    too_large: bool
    inns: list[str]
    messages: list[InboundMailMessage]
    replies: list[InboundMailReply]
    journal: list[InboundMailEvent]
    reply_all_copy: list[str]
    personal_label: str
    reply_to: str
    reply_options: list[str]


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
    to: str | None = Field(default=None, max_length=255)
    reply_all: bool = False
    awaiting: bool = False


class InboundMailTakeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    takeover: bool = False


class InboundMailBulkArchiveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ids: list[int] = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=3, max_length=500)


class InboundMailSkippedItem(_Out):
    id: int
    reason: Literal["in_work_by_other", "handled", "registering", "missing"]
    assignee: InboundMailPerson | None


class InboundMailBulkArchiveResult(_Out):
    archived: list[int]
    skipped: list[InboundMailSkippedItem]


def _lead(link: crm.InboundMailLink | None) -> InboundMailLink | None:
    if link is None:
        return None
    return InboundMailLink(id=link.id, number=lead_number(link.id), name=link.name)


def _client(link: crm.InboundMailLink | None) -> InboundMailLink | None:
    return InboundMailLink(id=link.id, number=str(link.id), name=link.name) if link else None


def _assist(src: crm.InboundMailAssist) -> InboundMailAssist:
    return InboundMailAssist.model_validate(src.model_dump(mode="json"))


def _person(src: crm.InboundMailPerson | None) -> InboundMailPerson | None:
    return InboundMailPerson(id=src.id, name=src.name) if src else None


def _result(src: crm.InboundMailResult | None, subject: str) -> InboundMailResult | None:
    if src is None:
        return None
    number = src.letter_number
    return InboundMailResult(
        outcome=src.outcome,
        by=_person(src.by),
        at=src.at,
        letter_number=number,
        letter_ref=letter_ref(number, subject).path if number else None,
        lead=_lead(src.lead),
        reason=src.reason,
    )


def to_item(src: crm.InboundMailItem | crm.InboundMailOut) -> InboundMailItem:
    return InboundMailItem(
        id=src.id,
        status=src.status,
        from_email=src.from_email,
        from_name=src.from_name,
        subject=src.subject,
        received_at=src.received_at,
        sent_at=src.sent_at,
        activity_at=src.activity_at,
        preview=src.preview,
        attachments_count=src.attachments_count,
        assist=_assist(src.assist),
        client=_client(src.client),
        lead=_lead(src.lead),
        from_history=bool(src.from_history),
        assignee=_person(src.assignee),
        assigned_at=src.assigned_at,
        personal=bool(src.personal),
        thread_reply=bool(src.thread_reply),
        unread=bool(src.unread),
        messages_count=src.messages_count,
        eds_waiting=bool(src.eds_waiting),
        result=_result(src.result, src.subject),
    )


def to_page(src: crm.InboundMailPage) -> InboundMailPage:
    return InboundMailPage(
        items=[to_item(i) for i in src.items],
        total=src.total,
        mailbox=InboundMailMailbox.model_validate(src.mailbox.model_dump(mode="json")),
        counts=InboundMailCounts.model_validate(src.counts.model_dump(mode="json")),
    )


def _address(src: crm.InboundMailAddress) -> InboundMailAddress:
    return InboundMailAddress(email=src.email, staff=_person(src.staff), mailbox=bool(src.mailbox))


def _file(src: crm.InboundMailAttachment) -> InboundMailAttachment:
    """`inline` у старого CRM (до P2-4) нет — тогда это обычное вложение."""
    return InboundMailAttachment(
        index=src.index,
        name=src.name,
        content_type=src.content_type,
        size=src.size,
        inline=bool(src.inline),
    )


def _message(src: crm.InboundMailMessage) -> InboundMailMessage:
    """Поля показа письма (`text_tail`, `html`, `html_remote_images`) у старого CRM (до P2-4)
    отсутствуют: BFF терпит порядок выкладки BFF → CRM."""
    return InboundMailMessage(
        id=src.id,
        from_email=src.from_email,
        from_name=src.from_name,
        at=src.at,
        text=src.text,
        text_tail=src.text_tail or "",
        html=src.html,
        new_participant=bool(src.new_participant),
        html_remote_images=src.html_remote_images or 0,
        attachments=[_file(a) for a in src.attachments],
    )


def to_mail(src: crm.InboundMailOut) -> InboundMail:
    return InboundMail(
        **to_item(src).model_dump(),
        to=[_address(a) for a in src.to],
        cc=[_address(a) for a in src.cc],
        text=src.text,
        attachments=[_file(a) for a in src.attachments],
        skipped=[InboundMailSkipped.model_validate(s.model_dump()) for s in src.skipped],
        too_large=src.too_large,
        inns=list(src.inns),
        messages=[_message(m) for m in src.messages],
        replies=[
            InboundMailReply(**{**r.model_dump(exclude={"by"}), "by": _person(r.by)})
            for r in src.replies
        ],
        journal=[
            InboundMailEvent(at=e.at, action=e.action, actor=_person(e.actor), detail=e.detail)
            for e in src.journal
        ],
        reply_all_copy=list(src.reply_all_copy),
        personal_label=src.personal_label,
        reply_to=src.reply_to,
        reply_options=list(src.reply_options),
    )


def to_bulk(src: crm.InboundMailBulkArchiveOut) -> InboundMailBulkArchiveResult:
    return InboundMailBulkArchiveResult(
        archived=list(src.archived),
        skipped=[
            InboundMailSkippedItem(id=s.id, reason=s.reason, assignee=_person(s.assignee))
            for s in src.skipped
        ],
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
