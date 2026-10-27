"""Модели «Клиенты · Ждут ответа» (контракт platform-bff.yaml 0.20.0, тег `messages`, D1-1).

Ответы собираются из ответов CRM (`crm_models`): очередь `GET /inbox` с запиской передачи (CRM-06),
карточка лида, переписка, заметки, команда. BFF переводит словарь (режим `owner_mode` CRM → `bot` /
`waiting` / `manager`, номер лида `L-NNNN`, сотрудник — `PersonRef`) и прячет то, что экрану не
нужно и не должно уйти в браузер: ключи хранилища вложений, служебные пометки причины (`dialog:
…`). Решения — у CRM.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.feeds.models import PersonRef

Language = Literal["ru", "uz", "en"]
OwnerMode = Literal["bot", "waiting", "manager"]
InboxGroup = Literal["handoff", "mine", "unassigned"]
Priority = Literal["hot", "warm", "info"]
HandoffState = Literal["open", "taken", "snoozed"]
Author = Literal["lead", "bot", "manager", "system"]
Timeline = Literal["<1m", "<3m", "<12m", ">12m"]
DecisionRole = Literal["decision_maker", "influencer", "researcher"]

CLIENT_MESSAGE_ID = r"^[A-Za-z0-9_-]{8,64}$"


class HandoffFacts(BaseModel):
    interest: list[str] = Field(default_factory=list)
    timeline: Timeline | None = None
    decision_role: DecisionRole | None = None
    budget_hint: str | None = None
    company: str | None = None
    company_size: str | None = None
    region: str | None = None


class HandoffNote(BaseModel):
    request: str | None
    facts: HandoffFacts
    last_message: str | None


class HandoffInfo(BaseModel):
    priority: Priority
    state: HandoffState
    reasons: list[str]
    reason_text: str | None
    recommendation: str | None
    created_at: datetime
    sla_due_at: datetime | None
    snoozed_until: datetime | None
    taken_by: PersonRef | None


class MessageInboxItem(BaseModel):
    lead: str
    name: str
    group: InboxGroup
    language: Language
    channel: str
    unread: bool
    last_message_at: datetime | None
    assigned: PersonRef | None
    handoff: HandoffInfo | None
    note: HandoffNote


class MessageInbox(BaseModel):
    items: list[MessageInboxItem]


class ConversationContacts(BaseModel):
    telegram: str | None
    phone: str | None
    email: str | None
    company: str | None


class ConversationCard(BaseModel):
    lead: str
    name: str
    language: Language
    channel: str
    owner_mode: OwnerMode
    assigned: PersonRef | None
    consent_given_at: datetime | None
    contacts: ConversationContacts
    facts: HandoffFacts
    request: str | None
    handoff: HandoffInfo | None
    client_in_erp: bool


class ThreadAttachment(BaseModel):
    index: int
    name: str
    mime: str
    size: int | None
    url: str | None


class ThreadMessage(BaseModel):
    id: int
    author: Author
    author_name: str | None
    text: str
    created_at: datetime
    attachments: list[ThreadAttachment]
    delivery: Literal["sending", "unconfirmed"] | None = None


class TeamNote(BaseModel):
    id: int
    author_name: str | None
    text: str
    created_at: datetime
    visible_to_bot: bool


class ConversationThread(BaseModel):
    items: list[ThreadMessage]
    notes: list[TeamNote]
    has_more: bool


class ReplyIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    client_message_id: str = Field(pattern=CLIENT_MESSAGE_ID)


class SentMessage(BaseModel):
    id: int


class TeamNoteIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


class AssistIn(BaseModel):
    mode: Literal["draft", "improve"]
    text: str | None = Field(default=None, max_length=4000)


class AssistSuggestion(BaseModel):
    text: str
    notice: Literal["numbers_removed", "new_numbers"] | None


class ReturnToBotIn(BaseModel):
    note: str | None = Field(default=None, max_length=4000)
