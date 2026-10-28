"""Перевод ответов CRM в модели «Клиенты · Клиенты» (W16-D1-2b): чистые функции без сети.

Ответы CRM о клиентах, контактах, сделках и документах разбираются здесь своими моделями: их нет
среди сгенерированных `crm_models` (корни генератора — экраны D1-1). Модели берут только нужные поля
и терпят лишние. Шаг пути и «что видит клиент» (`client-statuses.yaml`) — по стадии ERP, которую
CRM хранит у заявки (`external_stage`); номер ЗВ/ПР — из ERP (`erp_number`).
"""

from datetime import date, datetime
from typing import Any, Literal, get_args

from pydantic import BaseModel, ConfigDict

from app.clients import crm_models as crm
from app.crm_leads_view import invitation, status_of
from app.feeds.models import SourceState, StepCode
from app.feeds.numbers import lead_number
from app.schemas_crm_leads import (
    ClientCard,
    ClientContactView,
    ClientDocumentRow,
    ClientHandoff,
    ClientLeadLink,
    ClientRequestRow,
    ClientRow,
    ClientSees,
    ClientSources,
    ContactChannel,
    DocumentType,
)

_DOC_TYPES: tuple[str, ...] = get_args(DocumentType)
Handoff = Literal["pending", "done", "failed"]


class _Crm(BaseModel):
    model_config = ConfigDict(extra="ignore")


class CrmClientItem(_Crm):
    id: int
    name: str
    inn: str | None = None
    erp_company_id: int | None = None
    erp_handoff_status: Handoff | None = None
    open_deals: int = 0
    last_activity_at: datetime | None = None


class CrmLeadBrief(_Crm):
    id: int
    display_name: str
    stage: str
    created_at: datetime


class CrmIdentity(_Crm):
    tg_user_id: int
    tg_username: str | None = None


class CrmClientDetail(_Crm):
    id: int
    name: str
    inn: str | None = None
    segment: str | None = None
    erp_company_id: int | None = None
    erp_handoff_status: Handoff | None = None
    erp_handoff_error: str | None = None
    identities: list[CrmIdentity] = []
    leads: list[CrmLeadBrief] = []
    invitation: crm.InvitationOut | None = None


class CrmContact(_Crm):
    id: int
    full_name: str
    position: str | None = None
    phone_e164: str | None = None
    email: str | None = None
    telegram_identity_id: int | None = None
    is_primary: bool = False
    preferred_channel: Literal["email", "telegram", "both"] | None = None


class CrmSuggestion(_Crm):
    telegram_identity_id: int
    tg_username: str | None = None


class CrmContacts(_Crm):
    contacts: list[CrmContact] = []
    suggestions: list[CrmSuggestion] = []


class CrmDeal(_Crm):
    id: int
    title: str
    stage: str
    created_at: datetime
    external_stage: str | None = None
    erp_number: str | None = None
    request_summary: str | None = None
    request_urgency: Literal["normal", "urgent"] | None = None
    request_letter_file_id: str | None = None
    erp_request_status: Handoff | None = None
    erp_request_error: str | None = None


class CrmDocument(_Crm):
    id: int
    title: str
    type: str
    number: str | None = None
    doc_date: date | None = None
    is_visible_to_client: bool = False


class CrmRequestCreated(_Crm):
    client_id: int
    deal_id: int
    lead_id: int | None = None
    created: bool = True
    erp_request_status: Handoff = "pending"


class CrmRequestRetried(_Crm):
    client_id: int
    deal_id: int
    erp_request_status: Handoff = "pending"


# --- список ---------------------------------------------------------------------------------------


def client_row(item: CrmClientItem) -> ClientRow:
    return ClientRow(
        id=item.id,
        name=item.name,
        inn=item.inn,
        in_erp=item.erp_company_id is not None,
        open_requests=max(item.open_deals, 0),
        last_activity_at=item.last_activity_at,
        handoff_status=item.erp_handoff_status,
    )


def recent_first(rows: list[ClientRow]) -> list[ClientRow]:
    """Сначала недавно активные; без активности — в конце, в порядке CRM."""
    dated = sorted(
        (r for r in rows if r.last_activity_at is not None),
        key=lambda r: r.last_activity_at or datetime.min,
        reverse=True,
    )
    return dated + [r for r in rows if r.last_activity_at is None]


# --- карточка -------------------------------------------------------------------------------------

# Стадия ERP у заявки CRM (`external_stage`, события ERP) → шаг пути из 7.
_STEP: dict[str, StepCode] = {
    "request": "REQUEST",
    "quoting": "CALCULATION",
    "quote_sent": "QUOTE",
    "accepted": "CONTRACT",
    "contract": "CONTRACT",
    "invoiced": "PAYMENT",
    "paid": "PAYMENT",
    "fulfilment": "PAYMENT",
    "closing": "PAYMENT",
    "won": "DONE",
    "lost": "LOST",
}
_PROJECT: frozenset[StepCode] = frozenset({"CONTRACT", "PAYMENT", "DONE"})
# Что видит клиент: сначала точная стадия ERP, затем — по шагу.
_SEES_STAGE: dict[str, ClientSees] = {
    "invoiced": "awaiting_payment",
    "paid": "fulfilling",
    "fulfilment": "fulfilling",
    "closing": "awaiting_acceptance",
}
_SEES_STEP: dict[StepCode, ClientSees] = {
    "REQUEST": "in_work",
    "RESOLUTION": "in_work",
    "CALCULATION": "in_work",
    "QUOTE": "awaiting_decision",
    "CONTRACT": "contract_review",
    "PAYMENT": "awaiting_payment",
    "DONE": "done",
    "LOST": "rejected",
}


def step_of(deal: CrmDeal) -> StepCode:
    if deal.stage == "lost":
        return "LOST"
    if deal.stage == "won" and deal.external_stage is None:
        return "DONE"
    return _STEP.get(deal.external_stage or "", "REQUEST")


def request_row(deal: CrmDeal) -> ClientRequestRow:
    step = step_of(deal)
    sees = _SEES_STAGE.get(deal.external_stage or "") if step == "PAYMENT" else None
    return ClientRequestRow(
        deal=deal.id,
        number=deal.erp_number,
        title=deal.title,
        summary=deal.request_summary,
        step=step,
        project=step in _PROJECT,
        client_sees=sees or _SEES_STEP[step],
        urgency=deal.request_urgency,
        transfer=deal.erp_request_status,
        transfer_error=deal.erp_request_error,
        created_at=deal.created_at,
        letter_file_id=deal.request_letter_file_id,
    )


def document_row(doc: CrmDocument) -> ClientDocumentRow:
    kind = doc.type if doc.type in _DOC_TYPES else "other"
    return ClientDocumentRow(
        id=doc.id,
        title=doc.title,
        type=kind,
        number=doc.number,
        date=doc.doc_date,
        visible_to_client=doc.is_visible_to_client,
    )


def contact_view(contact: CrmContact, telegram: dict[int, str | None]) -> ClientContactView:
    """Каналы — по тому, что есть у контакта: Telegram привязан, телефон, e-mail."""
    username = (
        telegram.get(contact.telegram_identity_id)
        if contact.telegram_identity_id is not None
        else None
    )
    channels: list[ContactChannel] = []
    if contact.telegram_identity_id is not None:
        channels.append("telegram")
    if contact.phone_e164:
        channels.append("phone")
    if contact.email:
        channels.append("email")
    return ClientContactView(
        id=contact.id,
        name=contact.full_name,
        position=contact.position,
        phone=contact.phone_e164,
        email=contact.email,
        telegram=username.lstrip("@") if username else None,
        channels=channels,
        preferred_channel=contact.preferred_channel,
        is_primary=contact.is_primary,
    )


def telegram_names(detail: CrmClientDetail, contacts: CrmContacts) -> dict[int, str | None]:
    """Имя Telegram по id привязки: из подсказок CRM; у клиента одна привязка — её имя."""
    names: dict[int, str | None] = {
        s.telegram_identity_id: s.tg_username for s in contacts.suggestions
    }
    if len(detail.identities) == 1:
        only = detail.identities[0].tg_username
        for c in contacts.contacts:
            if c.telegram_identity_id is not None and not names.get(c.telegram_identity_id):
                names[c.telegram_identity_id] = only
    return names


def lead_link(brief: CrmLeadBrief) -> ClientLeadLink:
    return ClientLeadLink(
        lead=lead_number(brief.id),
        name=brief.display_name or lead_number(brief.id),
        status=status_of(None, brief.stage),
        last_message_at=None,
    )


def client_card(
    detail: CrmClientDetail,
    contacts: CrmContacts | None,
    deals: list[CrmDeal] | None,
    documents: list[CrmDocument] | None,
) -> ClientCard:
    """Карточка 360°; часть, которую CRM не отдала (`None`), — пустая и `unavailable`."""

    def state(part: Any) -> SourceState:
        return "ok" if part is not None else "unavailable"

    names = telegram_names(detail, contacts) if contacts is not None else {}
    return ClientCard(
        id=detail.id,
        name=detail.name,
        inn=detail.inn,
        segment=detail.segment,
        in_erp=detail.erp_company_id is not None,
        handoff=ClientHandoff(status=detail.erp_handoff_status, error=detail.erp_handoff_error),
        contacts=[contact_view(c, names) for c in contacts.contacts] if contacts else [],
        leads=[lead_link(b) for b in detail.leads],
        requests=[request_row(d) for d in deals or []],
        documents=[document_row(d) for d in documents or []],
        invitation=invitation(detail.invitation),
        sources=ClientSources(
            contacts=state(contacts), requests=state(deals), documents=state(documents)
        ),
    )
