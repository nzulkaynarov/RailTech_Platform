"""DTO лидов, переписки, входящих и действий (SPEC §10.1)."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class EscalationOut(BaseModel):
    id: int
    priority: str
    status: str
    reason_codes: list[str]
    reason_text: str | None
    recommendation: str | None
    taken_by_user_id: int | None
    taken_at: datetime | None
    sla_due_at: datetime | None
    snoozed_until: datetime | None
    created_at: datetime


class LeadOut(BaseModel):
    id: int
    display_name: str
    language: str
    stage: str
    score: int
    owner_mode: str
    assigned_user_id: int | None
    assigned_user_name: str | None = None
    client_id: int | None = None
    # Лид написал после последнего ответа менеджера (аудит P-23).
    unread: bool = False
    need_summary: str | None
    product_interest: list[str]
    last_lead_msg_at: datetime | None
    created_at: datetime
    escalation: EscalationOut | None = None


class LeadDetail(LeadOut):
    qualification: dict[str, Any]
    consent_given_at: datetime | None
    tg_username: str | None
    # Номер из кнопки «Поделиться номером» в боте (Q-020), E.164; удаляется по /delete.
    phone_e164: str | None = None
    notes_count: int
    snoozed_until: datetime | None
    # Открытый сервисный запрос лида или его клиента — ссылка из карточки (Q-017).
    open_service_request_id: int | None = None


class LeadPage(BaseModel):
    items: list[LeadOut]
    total: int


class MessageOut(BaseModel):
    id: int
    role: str
    text: str
    attachments: list[dict[str, Any]]
    sent_by_user_id: int | None
    created_at: datetime
    meta: dict[str, Any]


class NoteOut(BaseModel):
    id: int
    user_id: int | None
    text: str
    visible_to_bot: bool
    created_at: datetime


class InboxResponse(BaseModel):
    escalations: list[LeadOut]
    mine: list[LeadOut]
    unassigned: list[LeadOut]


class ReturnToBot(BaseModel):
    note: str | None = Field(default=None, max_length=4000)


class Snooze(BaseModel):
    until: datetime


class Assign(BaseModel):
    user_id: int


class TeamMember(BaseModel):
    id: int
    full_name: str


class Close(BaseModel):
    reason: str | None = Field(default=None, max_length=1000)


class NoteCreate(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    visible_to_bot: bool = False


class Reply(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


class AssistRequest(BaseModel):
    """ИИ-помощь при ответе (Q-019): `draft` — черновик, `improve` — правка текста `text`."""

    mode: Literal["draft", "improve"]
    text: str | None = Field(default=None, max_length=4000)


class AssistOut(BaseModel):
    """Текст для поля ответа (клиенту не отправляется). `notice`: `numbers_removed` — из
    черновика убраны предложения с числами не из базы знаний; `new_numbers` — правка добавила
    числа, возвращён исходный текст."""

    text: str
    cost_usd: float | None = None
    notice: Literal["numbers_removed", "new_numbers"] | None = None


class ActionResult(BaseModel):
    ok: Literal[True] = True
    id: int | None = None
