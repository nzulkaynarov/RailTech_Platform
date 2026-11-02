"""DTO входящей почты (W18A-P2, B-INB-5): очередь, карточка письма, действия, коннектор IMAP."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr

MailStatus = Literal["new", "spam", "registered", "lead", "archived"]
AssistStatus = Literal["none", "done", "unavailable", "off"]
AssistKind = Literal["buyer", "official", "supplier_doc", "other"]
AssistAction = Literal["register", "lead", "archive"]


class InboundMailAttachment(BaseModel):
    index: int
    name: str
    content_type: str
    size: int


class InboundMailSkipped(BaseModel):
    name: str
    reason: str = Field(
        description="type — тип не из белого списка, size — больше 25 МБ, count — больше 20"
    )


class InboundMailAssist(BaseModel):
    """Подсказка помощника (по кнопке «Подсказать»): тип, суть, предложенное действие. Ничего сама
    не делает; `none` — не запрашивали, `off` — помощник выключен админом."""

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
    from_history: bool = Field(
        default=False,
        description="Загружено «за период» и старше 3 дней: в списке, не строкой «Моих задач»",
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


class InboundMailCounts(BaseModel):
    """Числа вкладок списка: ждут разбора (из них «из истории») и подозрительные."""

    new: int
    history: int
    spam: int


class InboundMailPage(BaseModel):
    items: list[InboundMailItem]
    total: int
    mailbox: InboundMailbox
    counts: InboundMailCounts


class InboundMailArchiveIn(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class InboundMailReplyIn(BaseModel):
    text: str = Field(min_length=1, max_length=20000)


class InboundMailLeadOut(BaseModel):
    lead_id: int
    created: bool = Field(
        description="false — письмо добавлено заметкой в открытый лид с этим адресом"
    )


class ImapFolderIn(BaseModel):
    """Папка опроса: имя как на сервере (modified UTF-7), `spam` — письма «Подозрительные»."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    spam: bool = False


class ImapFolderOut(ImapFolderIn):
    label: str = Field(description="Имя для человека (modified UTF-7 раскодирован)")


class ImapServerFolder(BaseModel):
    name: str
    label: str
    junk: bool = Field(description="Сервер отметил папку флагом \\Junk (RFC 6154)")
    selectable: bool


class ImapFoldersOut(BaseModel):
    """«Найти папки»: список папок ящика (`LIST`) или причина словом-кодом."""

    ok: bool
    error_kind: str | None = None
    detail: str | None = None
    folders: list[ImapServerFolder] = Field(default_factory=list)
    spam_suggestion: str | None = Field(
        default=None, description="Спам-папка по флагу \\Junk или единственному привычному имени"
    )


class ImapHistoryIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    days: Literal[7, 14, 30, 90]


class ImapHistoryOut(BaseModel):
    """Загрузка писем за период: ход и итог. `found` — сколько берём (не больше 2000), `limited` —
    в периоде писем больше, взяты новые."""

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
    folders: list[ImapFolderOut] = Field(
        default_factory=list, description="Папки опроса; по умолчанию одна — `mailbox`"
    )
    history: ImapHistoryOut | None = Field(
        default=None, description="Последняя загрузка писем за период"
    )


class ImapConnectorIn(BaseModel):
    """Сохранение приёма: логин/пароль `None` — оставить прежние; пустой хост выключает приём."""

    model_config = ConfigDict(extra="forbid")

    host: str = Field(max_length=253)
    port: int = Field(default=993, ge=1, le=65535)
    security: Literal["ssl", "starttls"] = "ssl"
    mailbox: str = Field(default="INBOX", min_length=1, max_length=200)
    folders: list[ImapFolderIn] | None = Field(
        default=None,
        max_length=10,
        description="Папки опроса; `null` — прежние. Задано — `mailbox` = первая не спам",
    )
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
