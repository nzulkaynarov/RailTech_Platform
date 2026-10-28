"""Модели «Клиенты · Лиды», «Клиенты · Клиенты» и «+ Создать заявку» (контракт platform-bff.yaml
0.26.0, теги `leads`, `clients`, `requests`, W16-D1-2b).

Ответы собираются из ответов CRM: страница лидов `GET /leads`, карточка лида с последними
сообщениями, клиенты, карточка клиента 360° (контакты, лиды, заявки и проекты, документы),
приглашение в кабинет (D1-9), итог «Создать заявку» и «Повторить отправку в ERP». BFF переводит
словарь (номер лида `L-NNNN`, сотрудник — `PersonRef`, шаг пути и «что видит клиент» по стадии
ERP) и не отдаёт браузеру лишнего; решения — у CRM.
"""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.feeds.models import PersonRef, SourceState, StepCode
from app.schemas_crm_messages import ConversationContacts, HandoffFacts, HandoffInfo, Language

LeadTab = Literal["all", "new", "dialog", "wants_quote", "client"]
LeadScope = Literal["all", "mine", "overdue"]
LeadPlatformStatus = Literal["new", "dialog", "wants_quote", "no_answer", "client", "lost"]
NoticeStatus = Literal["queued", "sent", "failed", "skipped"]
InviteChannel = Literal["email", "telegram", "both"]
ConsentMethod = Literal["phone", "email", "paper"]
Transfer = Literal["pending", "done", "failed"]
Urgency = Literal["normal", "urgent"]
ContactChannel = Literal["telegram", "phone", "email"]
DocumentType = Literal["contract", "proposal", "letter", "invoice", "act", "other"]
ClientSees = Literal[
    "in_work",
    "awaiting_decision",
    "contract_review",
    "contract_signing",
    "awaiting_payment",
    "checking_payment",
    "fulfilling",
    "awaiting_acceptance",
    "done",
    "rejected",
    "quote_expired",
]

LEAD_PATTERN = r"^[Ll]-?\d{1,9}$"
UUID_PATTERN = r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"


# --- лиды -----------------------------------------------------------------------------------------


class LeadRow(BaseModel):
    lead: str
    name: str
    status: LeadPlatformStatus
    channel: str
    language: Language
    assigned: PersonRef | None
    need: str | None
    last_message_at: datetime | None
    unread: bool
    handoff_open: bool
    overdue: bool
    client_id: int | None


class LeadPage(BaseModel):
    items: list[LeadRow]
    total: int


class LeadMessagePreview(BaseModel):
    author: Literal["lead", "bot", "manager", "system"]
    text: str
    at: datetime


class LeadNotice(BaseModel):
    channel: str | None
    status: NoticeStatus
    sent_at: datetime | None
    error_text: str | None


class ClientInvitation(BaseModel):
    status: NoticeStatus
    channel: str | None
    sent_via: list[str]
    sent_at: datetime | None
    contact_name: str | None
    error_text: str | None
    available_channels: list[InviteChannel]
    suggested_channel: InviteChannel | None
    can_resend: bool


class ClientShort(BaseModel):
    id: int
    name: str
    inn: str | None


class LeadConsent(BaseModel):
    given_at: datetime | None
    method: ConsentMethod | None


class LeadFirstResponse(BaseModel):
    due_at: datetime | None
    overdue: bool


class LeadCard(BaseModel):
    lead: str
    name: str
    status: LeadPlatformStatus
    channel: str
    language: Language
    assigned: PersonRef | None
    contacts: ConversationContacts
    consent: LeadConsent
    facts: HandoffFacts
    need: str | None
    interest: list[str]
    handoff: HandoffInfo | None
    last_messages: list[LeadMessagePreview]
    client: ClientShort | None
    confirmation: LeadNotice | None
    first_response: LeadFirstResponse
    invitation: ClientInvitation | None


# --- клиенты --------------------------------------------------------------------------------------


class ClientRow(BaseModel):
    id: int
    name: str
    inn: str | None
    in_erp: bool
    open_requests: int
    last_activity_at: datetime | None
    handoff_status: Transfer | None


class ClientList(BaseModel):
    items: list[ClientRow]


class ClientContactView(BaseModel):
    id: int
    name: str
    position: str | None
    phone: str | None
    email: str | None
    telegram: str | None
    channels: list[ContactChannel]
    preferred_channel: InviteChannel | None
    is_primary: bool


class ClientLeadLink(BaseModel):
    lead: str
    name: str
    status: LeadPlatformStatus
    last_message_at: datetime | None


class ClientRequestRow(BaseModel):
    deal: int
    number: str | None
    title: str
    summary: str | None
    step: StepCode
    project: bool
    client_sees: ClientSees
    urgency: Urgency | None
    transfer: Transfer | None
    transfer_error: str | None
    created_at: datetime
    letter_file_id: str | None


class ClientDocumentRow(BaseModel):
    id: int
    title: str
    type: DocumentType
    number: str | None
    date: date | None
    visible_to_client: bool


class ClientHandoff(BaseModel):
    status: Transfer | None
    error: str | None


class ClientSources(BaseModel):
    contacts: SourceState
    requests: SourceState
    documents: SourceState


class ClientCard(BaseModel):
    id: int
    name: str
    inn: str | None
    segment: str | None
    in_erp: bool
    handoff: ClientHandoff
    contacts: list[ClientContactView]
    leads: list[ClientLeadLink]
    requests: list[ClientRequestRow]
    documents: list[ClientDocumentRow]
    invitation: ClientInvitation | None
    sources: ClientSources


class InvitationResendIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    channel: InviteChannel
    contact_id: int | None = None


# --- «+ Создать заявку» ---------------------------------------------------------------------------


class RequestCompanyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    inn: str | None = Field(default=None, max_length=32)


class RequestContactFormIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contact_id: int | None = None
    full_name: str | None = Field(default=None, max_length=255)
    position: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=32)
    email: str | None = Field(default=None, max_length=255)
    use_lead_telegram: bool = False


class RequestConsentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method: ConsentMethod
    comment: str | None = Field(default=None, max_length=500)


class RequestFormIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_key: str = Field(pattern=UUID_PATTERN)
    lead: str | None = Field(default=None, pattern=LEAD_PATTERN)
    client_id: int | None = None
    company: RequestCompanyIn | None = None
    contact: RequestContactFormIn
    summary: str = Field(min_length=1, max_length=5000)
    urgency: Urgency
    letter_file_id: str | None = Field(default=None, pattern=UUID_PATTERN)
    consent: RequestConsentIn | None = None


class RequestCreatedView(BaseModel):
    client_id: int
    deal: int
    lead: str | None
    created: bool
    transfer: Transfer


class RequestRetriedView(BaseModel):
    deal: int
    client_id: int
    transfer: Transfer


class RequestFileFromMessageIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lead: str = Field(pattern=LEAD_PATTERN)
    message: int = Field(ge=1)
    index: int = Field(ge=0)
