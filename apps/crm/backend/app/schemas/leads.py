"""DTO лидов, переписки, входящих и действий (SPEC §10.1)."""

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.notices import InvitationOut, NoticeOut


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


class HandoffFacts(BaseModel):
    """Факты квалификации от бота (коды CRM: срок `<1m|<3m|<12m|>12m`, роль `decision_maker|…`)."""

    interest: list[str] = Field(default_factory=list)  # названия продуктов из справочника
    timeline: str | None = None
    decision_role: str | None = None
    budget_hint: str | None = None
    company: str | None = None
    company_size: str | None = None
    region: str | None = None


class HandoffNote(BaseModel):
    """Записка передачи (CRM-06, D1-1): запрос, факты, причина, рекомендуемый шаг — как в
    карточке канала команды, без сырых кодов продуктов. Причины — коды `reason_codes`
    (подписи — у экрана)."""

    request: str | None = None
    facts: HandoffFacts = Field(default_factory=HandoffFacts)
    reason_codes: list[str] = Field(default_factory=list)
    reason_text: str | None = None
    recommendation: str | None = None
    # Последнее сообщение лида, до 200 символов (как в карточке канала).
    last_lead_message: str | None = None


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
    # Откуда пришёл лид (M3-CRM-05): telegram | web | phone | email | referral (| sandbox).
    source: str = "telegram"
    # Статус лида для Платформы (CRM-02, W16-D1-2): вкладки «Лиды» —
    # docs/architecture/integration-map.md §3.1. CRM заполняет всегда; `null` — терпимый читатель
    # (строковое умолчание у перечисления ломало типы сгенерированных моделей BFF).
    platform_status: (
        Literal["new", "dialog", "wants_quote", "no_answer", "client", "lost"] | None
    ) = None

    # Записка передачи — только в `GET /inbox` (CRM-06); в остальных выдачах null.
    handoff_note: HandoffNote | None = None


class LeadDetail(LeadOut):
    qualification: dict[str, Any]
    consent_given_at: datetime | None
    # Как получено согласие, если его отметил сотрудник: phone | email | paper (D-8); у согласия
    # из бота и формы — null.
    consent_method: str | None = None
    tg_username: str | None
    # Номер из карточки (сайт/звонок/почта) или из кнопки «Поделиться номером» в боте (Q-020),
    # E.164; удаляется по /delete.
    phone_e164: str | None = None
    # Контакты лида без Telegram (M3-CRM-05).
    email: str | None = None
    company_name: str | None = None
    # Телефон основного контакта клиента, если лид привязан к клиенту (Q-011).
    client_phone_e164: str | None = None
    notes_count: int
    snoozed_until: datetime | None
    # Открытый сервисный запрос лида или его клиента — ссылка из карточки (Q-017).
    open_service_request_id: int | None = None
    # Режим бэк-офиса и привязки к ERP (ADR-0022, M3-CRM-03)
    backoffice_mode: str = "local"
    erp_company_id: int | None = None
    erp_deal_id: int | None = None
    # Клиент лида уже в ERP (есть `erp_company_id`); `False` и у лида без клиента (FIX-34b).
    client_in_erp: bool = False
    # Состояние передачи клиента лида в бэк-офис (FIX-31, `clients.erp_handoff_*`).
    client_handoff_status: Literal["pending", "done", "failed"] | None = None
    client_handoff_error: str | None = None
    # Запрос с сайта (D1-9): срок первого ответа, пока лид без ответственного (иначе null), и
    # просрочен ли он.
    first_response_due_at: datetime | None = None
    first_response_overdue: bool = False
    # Подтверждение запроса клиенту: канал, итог, причина словами (null — не заводилось).
    confirmation: NoticeOut | None = None
    # Приглашение клиента лида в кабинет: итог, каналы контакта, «повторить другим каналом» (null —
    # клиента нет).
    invitation: InvitationOut | None = None


class LeadPage(BaseModel):
    items: list[LeadOut]
    total: int


class MessageOut(BaseModel):
    id: int
    role: str
    text: str
    # Вложения сообщения по порядку: `kind`, `name`, `mime`, `size`, `stored` (файл сохранён),
    # `too_large`/`note` (почему не сохранён). Ключа хранилища нет (D1-8, B-014): файл отдаёт только
    # `GET /leads/{lead_id}/messages/{message_id}/attachments/{index}` по номеру в этом списке.
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
    """Сотрудник в выборе («кому передать лида», «исполнитель зоны»): без почты, телефона, ролей."""

    id: int
    full_name: str
    # Первые буквы имени и фамилии (до двух, заглавные); нет имени — первая буква почты (D1-8).
    initials: str = Field(max_length=3)
    position: str | None = None


class Close(BaseModel):
    reason: str | None = Field(default=None, max_length=1000)
    # Сделка лида (ADR-0019): сумма — необязательно; причина отказа — из справочника «Настроек».
    amount: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    lost_reason: str | None = Field(default=None, max_length=120)


class NoteCreate(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    visible_to_bot: bool = False


class Reply(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    # Ключ повтора от экрана (D1-1): тот же ключ — тот же ответ, второго сообщения клиенту нет.
    client_message_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{8,64}$")


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
