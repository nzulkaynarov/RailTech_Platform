"""DTO входящей почты (W18A-P2, B-INB-5): очередь, карточка письма, действия, коннектор IMAP."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr

MailStatus = Literal["new", "registered", "lead", "archived"]
AssistStatus = Literal["pending", "done", "unavailable", "off"]
AssistKind = Literal["buyer", "official", "supplier_doc", "other"]
AssistAction = Literal["register", "lead", "archive"]


class InboundMailAttachment(BaseModel):
    index: int
    name: str
    content_type: str
    size: int


class InboundMailSkipped(BaseModel):
    name: str
    reason: Literal["type", "size", "count"]


class InboundMailAssist(BaseModel):
    """Подсказка помощника: тип, суть, предложенное действие. Ничего сама не делает."""

    status: AssistStatus
    kind: AssistKind | None = None
    summary: str | None = None
    action: AssistAction | None = None


class InboundMailLink(BaseModel):
    id: int
    name: str


class InboundMailItem(BaseModel):
    id: int
    status: MailStatus
    from_email: str
    from_name: str
    subject: str
    received_at: datetime
    sent_at: datetime | None
    preview: str = Field(description="Начало текста письма (до 200 символов)")
    attachments_count: int
    assist: InboundMailAssist
    client: InboundMailLink | None = None
    lead: InboundMailLink | None = Field(
        default=None, description="Открытый лид с этим адресом (связка) или лид-итог"
    )


class InboundMailReply(BaseModel):
    id: int
    to_email: str
    subject: str
    status: str
    created_at: datetime
    sent_at: datetime | None


class InboundMailOut(InboundMailItem):
    to: list[str]
    text: str
    attachments: list[InboundMailAttachment]
    skipped: list[InboundMailSkipped]
    too_large: bool
    inns: list[str]
    eds_letter_id: str | None
    eds_letter_number: str | None
    result_lead: InboundMailLink | None
    archive_reason: str | None
    handled_at: datetime | None
    handled_by: int | None
    replies: list[InboundMailReply]


class InboundMailbox(BaseModel):
    """Состояние приёма для подсказки в очереди и строки здоровья."""

    configured: bool
    last_poll_at: datetime | None = None
    last_ok_at: datetime | None = None
    last_error_kind: str | None = None


class InboundMailPage(BaseModel):
    items: list[InboundMailItem]
    total: int
    mailbox: InboundMailbox


class InboundMailArchiveIn(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class InboundMailReplyIn(BaseModel):
    text: str = Field(min_length=1, max_length=20000)


class InboundMailLeadOut(BaseModel):
    lead_id: int
    created: bool = Field(
        description="false — письмо добавлено заметкой в открытый лид с этим адресом"
    )


class ImapStatusOut(BaseModel):
    """Приём почты: несекретное и состояние секретов (только на запись)."""

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


class ImapConnectorIn(BaseModel):
    """Сохранение приёма: логин/пароль `None` — оставить прежние; пустой хост выключает приём."""

    model_config = ConfigDict(extra="forbid")

    host: str = Field(max_length=253)
    port: int = Field(default=993, ge=1, le=65535)
    security: Literal["ssl", "starttls"] = "ssl"
    mailbox: str = Field(default="INBOX", min_length=1, max_length=200)
    assist_enabled: bool = True
    username: str | None = Field(default=None, max_length=255)
    imap_password: SecretStr | None = Field(default=None, min_length=1, max_length=512)
    password: SecretStr = Field(min_length=1, max_length=256)


class ImapCheckOut(BaseModel):
    """«Проверить приём»: ок или причина словом-кодом (без исключения — без нового `Reason`)."""

    ok: bool
    error_kind: str | None = None
    detail: str | None = None
    messages: int | None = None
    latency_ms: int | None = None
