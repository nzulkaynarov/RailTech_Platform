"""DTO входящей почты (W18A-P2, B-INB-5): очередь, карточка письма, действия, коннектор IMAP."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from app.schemas.mail_types import InboundMailType

MailStatus = Literal["new", "in_work", "registering", "done", "spam"]
MailOutcome = Literal["registered", "lead", "replied", "archived", "price", "handled"]
MailView = Literal["new", "mine", "in_work", "done", "spam", "all", "tasks"]
AssistStatus = Literal["none", "done", "unavailable", "off"]
AssistKind = Literal["buyer", "official", "supplier_doc", "other"]
AssistAction = Literal["register", "lead", "archive"]


class InboundMailAttachment(BaseModel):
    index: int
    name: str
    content_type: str
    size: int
    inline: bool = Field(
        default=False, description="Картинка встроена в письмо — в списке вложений не показывается"
    )


class InboundMailSkipped(BaseModel):
    name: str
    reason: str = Field(
        description="type — тип не из белого списка, size — больше 25 МБ, count — больше 20"
    )


class InboundMailAssist(BaseModel):
    """Подсказка помощника (по кнопке «Подсказать»): суть письма и тип. Ничего сама не делает;
    `none`
    — не
    запрашивали, `off` — помощник выключен админом. Тип письма — `InboundMailItem.type` (справочник
    «Типы входящих писем»); `kind` и `action` — устаревшие поля до MAIL-TYPES, у новых подсказок
    `null`."""

    status: AssistStatus
    kind: AssistKind | None = None
    summary: str | None = None
    action: AssistAction | None = None


class InboundMailLink(BaseModel):
    id: int
    name: str


class InboundMailPerson(BaseModel):
    id: int
    name: str


class InboundMailResult(BaseModel):
    """Итог «Разобрано»: что сделано, кто и когда; ВХ и лид — для ссылки из списка."""

    outcome: MailOutcome | None = Field(
        description="registered — ВХ, lead — лид или заметка, replied — ответ отправлен, "
        "archived — в архив с причиной, price — прайс или КП поставщика загружен, handled — "
        "переданное письмо обработал исполнитель; `null` у писем, "
        "разобранных до W18A-P2-3"
    )
    by: InboundMailPerson | None = None
    at: datetime | None = None
    letter_number: str | None = None
    lead: InboundMailLink | None = None
    reason: str | None = Field(default=None, description="Причина архива")


class InboundMailItem(BaseModel):
    id: int
    status: MailStatus
    from_email: str
    from_name: str
    subject: str
    received_at: datetime
    sent_at: datetime | None
    activity_at: datetime = Field(description="Время последнего входящего письма записи")
    preview: str = Field(description="Начало текста письма (до 200 символов)")
    attachments_count: int
    assist: InboundMailAssist
    type: InboundMailType | None = Field(
        default=None, description="Тип письма из справочника; `null` — не определён"
    )
    sender_check: Literal["unverified", "unknown"] | None = Field(
        default=None,
        description="Правило «отправитель → тип» не применено: `unverified` — отправитель не "
        "подтверждён (SPF/DKIM/DMARC не прошли), `unknown` — проверить нельзя (нет заголовка "
        "`Authentication-Results`)",
    )
    client: InboundMailLink | None = None
    lead: InboundMailLink | None = Field(
        default=None, description="Открытый лид с этим адресом (связка) или лид-итог"
    )
    from_history: bool = Field(
        default=False,
        description="Загружено «за период» и старше 3 дней: в списке, не строкой «Моих задач»",
    )
    assignee: InboundMailPerson | None = Field(
        default=None,
        description="«В работе у …»; у `new` с `thread_reply` — прежний исполнитель, справкой",
    )
    assigned_at: datetime | None = None
    personal: bool = Field(default=False, description="Адресовано лично сотруднику (правило ящика)")
    thread_reply: bool = Field(
        default=False, description="«Новое (ответ в цепочке)»: клиент ответил на разобранное"
    )
    unread: bool = Field(default=False, description="Не прочитано этим сотрудником")
    messages_count: int = Field(default=1, description="Входящих писем в записи (цепочка)")
    eds_waiting: bool = Field(
        default=False, description="Регистрация начата, событие о ВХ не пришло в срок"
    )
    result: InboundMailResult | None = Field(default=None, description="Итог у `done`")


class InboundMailReply(BaseModel):
    id: int
    to_email: str
    subject: str
    status: str
    created_at: datetime
    sent_at: datetime | None
    by: InboundMailPerson | None = None


class InboundMailAddress(BaseModel):
    """Адрес письма: сотрудник CRM по адресу и/или сам общий ящик."""

    email: str
    staff: InboundMailPerson | None = None
    mailbox: bool = False


class InboundMailMessage(BaseModel):
    """Входящее письмо записи (первое — корень); вложения качаются по `id` письма."""

    id: int
    from_email: str
    from_name: str
    at: datetime
    text: str = Field(description="Текст без цитаты и подписи, нормализованный")
    text_tail: str = Field(
        default="", description="Цитата прошлой переписки и подпись — свёрнуты под «…»"
    )
    html: str | None = Field(
        default=None,
        description="Безопасная HTML-версия (санитизация на сервере; показывать только в iframe "
        "с sandbox без скриптов и строгим CSP); внешние картинки без src — адрес в data-rt-src; "
        "нет — письмо без HTML или слишком большое",
    )
    html_remote_images: int = Field(
        default=0, description="Сколько внешних картинок ждут кнопки «Показать»"
    )
    attachments: list[InboundMailAttachment]
    new_participant: bool = Field(
        default=False,
        description="Письмо от адреса, которого в цепочке не было («новый участник переписки»)",
    )


class InboundMailEvent(BaseModel):
    """Строка журнала письма: действие кодом (подпись — на стороне интерфейса)."""

    at: datetime
    action: str
    actor: InboundMailPerson | None = None
    detail: str | None = None


class InboundMailOut(InboundMailItem):
    to: list[InboundMailAddress]
    cc: list[InboundMailAddress]
    text: str
    attachments: list[InboundMailAttachment]
    skipped: list[InboundMailSkipped]
    too_large: bool
    inns: list[str]
    eds_letter_id: str | None
    messages: list[InboundMailMessage] = Field(
        description="Все входящие письма записи по времени, корень первым"
    )
    replies: list[InboundMailReply] = Field(description="Наши ответы из журнала почты")
    journal: list[InboundMailEvent]
    reply_all_copy: list[str] = Field(
        description="Кому уйдёт копия при «Ответить всем» (без общего ящика и отправителя)"
    )
    personal_label: str = Field(description="Пометка «адресовано лично» из настроек")
    reply_to: str = Field(description="Кому ответ по умолчанию: отправитель корня цепочки")
    reply_options: list[str] = Field(
        description="Кому можно ответить: адреса цепочки (кроме общего ящика)"
    )


class InboundMailbox(BaseModel):
    """Состояние приёма для подсказки в очереди и строки здоровья."""

    configured: bool
    last_poll_at: datetime | None = None
    last_ok_at: datetime | None = None
    last_error_kind: str | None = None
    personal_label: str = Field(
        default="Адресовано лично", description="Пометка письма «адресовано лично» (настройка)"
    )


class InboundMailCounts(BaseModel):
    """Числа вкладок в рамках прав сотрудника: новые (из них «из истории»), мои в работе, все в
    работе, разобранные, подозрительные, все."""

    new: int
    history: int
    mine: int
    in_work: int
    done: int
    spam: int
    all: int
    unread_new: int = Field(description="Новых, которые этот сотрудник ещё не открывал")


class InboundMailPage(BaseModel):
    items: list[InboundMailItem]
    total: int
    mailbox: InboundMailbox
    counts: InboundMailCounts


class InboundMailArchiveIn(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class InboundMailReplyIn(BaseModel):
    text: str = Field(min_length=1, max_length=20000)
    to: str | None = Field(
        default=None,
        max_length=255,
        description="Кому: один из `reply_options` карточки; не задан — `reply_to`",
    )
    reply_all: bool = Field(
        default=False, description="«Ответить всем»: копия — остальные адреса письма"
    )
    awaiting: bool = Field(
        default=False,
        description="«Ждём ответа»: письмо остаётся «в работе», а не «Разобрано: ответ отправлен»",
    )


class InboundMailTakeIn(BaseModel):
    takeover: bool = Field(
        default=False, description="«Забрать себе» у того, кто уже ведёт письмо (журнал)"
    )


class InboundMailRegistrationIn(BaseModel):
    state: Literal["start", "cancel"] = Field(
        description="start — ВХ создаётся в EDS (письмо «Регистрируется»); cancel — EDS отказал"
    )


class InboundMailBulkArchiveIn(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=3, max_length=500)


class InboundMailSkippedItem(BaseModel):
    id: int
    reason: Literal["in_work_by_other", "handled", "registering", "missing"]
    assignee: InboundMailPerson | None = None


class InboundMailBulkArchiveOut(BaseModel):
    archived: list[int]
    skipped: list[InboundMailSkippedItem]


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
    personal_rule: bool = Field(
        default=True,
        description="«Адресовано лично»: сотрудник в «Кому», ящик в копии — письмо ему",
    )
    personal_label: str = Field(default="Адресовано лично", description="Пометка у такого письма")
    trusted_auth_servers: list[str] = Field(
        default_factory=list,
        description="Доверенные `authserv-id` почтовых серверов (домен с поддоменами): только их "
        "`Authentication-Results` подтверждает отправителя для правил «отправитель → тип»; "
        "пусто — выводится из хоста IMAP (см. `trusted_auth_effective`)",
    )
    trusted_auth_effective: list[str] = Field(
        default_factory=list,
        description="Кому верим на самом деле: заданный список или серверы провайдера нашего "
        "ящика по хосту IMAP; пусто — никому (хост не из известных провайдеров)",
    )
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
    personal_rule: bool = True
    personal_label: str = Field(default="Адресовано лично", min_length=1, max_length=80)
    trusted_auth_servers: list[str] | None = Field(
        default=None,
        max_length=30,
        description="Доверенные `authserv-id`; `null` — прежние, пустой список — по хосту IMAP",
    )
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
