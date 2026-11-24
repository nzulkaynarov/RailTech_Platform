"""Органайзер · Люди: лиды (PL-1, контракт BFF, тег `chats`).

Лид в «Людях» — человек, который ещё не стал клиентом. BFF просит у CRM только таких: статусы
«новый, в диалоге, просит КП, без ответа» и каналы людей (не чат Cabinet и не пробный).
Проигранные — только с `closed=true`. Телефон, почта и Telegram в список не входят: их
открывает `reveal` — сначала запись `contact.reveal` в журнал CRM (объект `lead`), потом лид;
журнал не принял запись — контактов нет (как у людей контрагентов).
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, status
from pydantic import BaseModel, ConfigDict

from app.api.crm_messages import _Crm, _lead_id
from app.clients import crm_models as crm
from app.crm_leads_view import status_of
from app.crm_messages_view import channel, language, person
from app.deps import Authed, require_any
from app.errors import PlatformError
from app.feeds.models import PersonRef
from app.feeds.numbers import lead_number
from app.schemas_crm_leads import LeadPlatformStatus
from app.schemas_crm_messages import Language

router = APIRouter(tags=["chats"])

API = "/api/v1"
Reader = Annotated[
    Authed, Depends(require_any(("crm.leads", "read"), ("crm.leads.triage", "full")))
]
LeadParam = Annotated[str, Path(pattern=r"^[Ll]-?\d{1,9}$")]

# Каналы, где лид — человек: чат Cabinet (`cabinet`, имя — название компании) и пробный
# (`sandbox`) в «Людей» не попадают.
PEOPLE_SOURCES = "telegram,web,phone,email,referral"
OPEN_STATUSES = "new,dialog,wants_quote,no_answer"
LEADS_LIMIT = 100


class PeopleLead(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lead: str
    name: str
    company: str | None
    status: LeadPlatformStatus
    channel: str
    language: Language
    assigned: PersonRef | None
    need: str | None
    has_phone: bool
    has_email: bool
    has_telegram: bool


class PeopleLeadPage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[PeopleLead]
    total: int


class PeopleLeadContacts(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lead: str
    phone: str | None
    email: str | None
    telegram: str | None


def _text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def to_people_lead(lead: crm.LeadOut) -> PeopleLead:
    raw = getattr(lead.platform_status, "value", lead.platform_status)
    return PeopleLead(
        lead=lead_number(lead.id),
        name=lead.display_name or lead_number(lead.id),
        company=_text(lead.company_name),
        status=status_of(raw if isinstance(raw, str) else None, lead.stage),
        channel=channel(lead.source),
        language=language(lead.language),
        assigned=person(lead.assigned_user_id, {}, lead.assigned_user_name),
        need=lead.need_summary,
        has_phone=bool(lead.has_phone),
        has_email=bool(lead.has_email),
        has_telegram=bool(lead.has_telegram),
    )


@router.get("/people/leads", response_model=PeopleLeadPage, operation_id="listPeopleLeads")
async def list_people_leads(authed: Reader, closed: bool = False) -> PeopleLeadPage:
    params = {
        "platform_status": f"{OPEN_STATUSES},lost" if closed else OPEN_STATUSES,
        "source": PEOPLE_SOURCES,
        "limit": LEADS_LIMIT,
    }
    raw = await _Crm(authed).json("GET", f"{API}/leads", params=params)
    body = raw if isinstance(raw, dict) else {}
    leads = [crm.LeadOut.model_validate(item) for item in body.get("items") or []]
    total = body.get("total")
    return PeopleLeadPage(
        items=[to_people_lead(lead) for lead in leads],
        total=total if isinstance(total, int) and total >= 0 else len(leads),
    )


@router.post(
    "/people/leads/{lead}/reveal",
    response_model=PeopleLeadContacts,
    operation_id="revealLeadContacts",
)
async def reveal_lead_contacts(lead: LeadParam, authed: Reader) -> PeopleLeadContacts:
    lead_id = _lead_id(lead)
    api = _Crm(authed)
    detail = crm.LeadDetail.model_validate(await api.json("GET", f"{API}/leads/{lead_id}"))
    # Сначала журнал: показ без записи «кто, когда, чьи» не допускается.
    try:
        response = await authed.call(
            "crm",
            "POST",
            f"{API}/audit/contact-reveal",
            json={
                "contact": str(lead_id),
                "name": detail.display_name or lead_number(lead_id),
                "kind": "lead",
            },
        )
        recorded = response.status_code == status.HTTP_204_NO_CONTENT
    except PlatformError:
        recorded = False
    if not recorded:
        raise PlatformError(
            "BACKEND_UNAVAILABLE",
            "Журнал недоступен — контакты не показаны, повторите чуть позже.",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    username = _text(detail.tg_username)
    return PeopleLeadContacts(
        lead=lead_number(lead_id),
        phone=_text(detail.phone_e164),
        email=_text(detail.email),
        telegram=f"@{username.lstrip('@')}" if username else None,
    )
