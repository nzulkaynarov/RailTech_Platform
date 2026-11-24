"""PL-3: a repeat request does not lose data; channels are glued only by exact matches.

Items: G3 (repeat web request fills empty fields, keeps differing ones as a fact), bot phone merge
carries origin and consent facts, «Новый лид» checks the client's e-mail, a web request from a
client contact attaches to the client's open lead.
"""

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.main import create_app
from app.models.auth import AuditLog
from app.models.clients import Client, ClientContact
from app.models.leads import Lead, LeadNote
from app.services.client_bot import ClientBotService
from app.services.settings import SettingsService
from tests.integration.crm_helpers import escalated_lead, login, make_user
from tests.integration.test_lead_intake import PHONE, web_body

pytestmark = pytest.mark.integration


@pytest.fixture
def client(live_settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(live_settings)) as test_client:
        yield test_client


def post_web(client: TestClient, settings: Settings, **patch: Any) -> int:
    response = client.post("/api/v1/leads/web", json=web_body(settings, **patch))
    assert response.status_code == 202, response.text
    return int(response.json()["lead_id"])


async def one_lead(sessions: async_sessionmaker[AsyncSession], lead_id: int) -> Lead:
    async with sessions() as session:
        return (await session.scalars(select(Lead).where(Lead.id == lead_id))).one()


async def test_repeat_request_fills_empty_fields_and_keeps_new_contacts_as_fact(
    client: TestClient, sessions: async_sessionmaker[AsyncSession], live_settings: Settings
) -> None:
    first = post_web(client, live_settings, email=None, company=None)
    assert (await one_lead(sessions, first)).email is None

    second = post_web(
        client,
        live_settings,
        email="Boss@Rail.uz",
        company="ООО Рельс",
        form="Pricing",
        page="/pos?utm_source=tg",
        utm={"utm_source": "tg", "utm_campaign": "nov"},
        landing_language="en",
    )
    assert second == first
    lead = await one_lead(sessions, first)
    assert (lead.email, lead.company_name) == ("boss@rail.uz", "ООО Рельс")
    fact = lead.qualification["repeat_requests"][-1]
    assert fact["kind"] == "repeat"
    assert fact["filled"] == ["company_name", "email"]
    assert fact["form"] == "pricing"
    assert fact["page"] == "/pos"
    assert fact["utm"] == {"utm_source": "tg", "utm_campaign": "nov"}
    assert fact["landing_language"] == "en"
    assert fact["consent_version"] == "web-form"
    assert "new_contacts" not in fact

    # Third request: stored values differ — never overwritten, kept as a fact and in the note.
    third = post_web(client, live_settings, email="other@rail.uz", company="Другая", text="Ещё раз")
    assert third == first
    lead = await one_lead(sessions, first)
    assert (lead.email, lead.company_name) == ("boss@rail.uz", "ООО Рельс")
    fact = lead.qualification["repeat_requests"][-1]
    assert fact["new_contacts"] == {"email": "other@rail.uz", "company_name": "Другая"}
    assert fact["filled"] == []
    async with sessions() as session:
        notes = (await session.scalars(select(LeadNote.text).order_by(LeadNote.id))).all()
        audit = (
            await session.scalars(
                select(AuditLog).where(AuditLog.action == "lead.web_request").order_by(AuditLog.id)
            )
        ).all()
    assert "other@rail.uz" in notes[-1]
    assert "Ещё раз" in notes[-1]
    assert audit[0].after is not None
    assert audit[0].after["filled"] == {"email": "boss@rail.uz", "company_name": "ООО Рельс"}
    assert audit[1].after is not None
    assert audit[1].after["new_contacts"] == {"email": "other@rail.uz", "company_name": "Другая"}

    manager, password = await make_user(sessions, "pl3-mgr@railtech.uz", ["manager"])
    detail = client.get(
        f"/api/v1/leads/{first}", headers=login(client, manager.email, password)
    ).json()
    assert len(detail["qualification"]["repeat_requests"]) == 2


async def test_bot_phone_merge_carries_origin_and_consent_facts(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """The survivor (earlier card) has no origin and no consent version; the absorbed Telegram
    card has them — they are carried, not dropped."""
    async with sessions() as session, session.begin():
        survivor = Lead(
            display_name="Звонок",
            source="phone",
            stage="in_progress",
            owner_mode="human",
            phone_e164=PHONE,
        )
        session.add(survivor)
        await session.flush()
        survivor_id = survivor.id
    tg_id = await escalated_lead(sessions, tg_user_id=5101)
    async with sessions() as session, session.begin():
        tg = (await session.scalars(select(Lead).where(Lead.id == tg_id))).one()
        tg.source_form, tg.source_page = "bot-start", "/pos"
        tg.source_utm = {"utm_source": "tg"}
        tg.source_lang = "ru"
        tg.consent_version, tg.consent_method = "v3", None
    await ClientBotService(sessions, SettingsService(sessions, ttl_s=0)).save_phone(5101, PHONE)

    lead = await one_lead(sessions, survivor_id)
    assert (lead.source_form, lead.source_page, lead.source_lang) == ("bot-start", "/pos", "ru")
    assert lead.source_utm == {"utm_source": "tg"}
    assert lead.consent_given_at is not None
    assert lead.consent_version == "v3"


async def test_manual_lead_conflicts_with_client_by_email(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    manager, password = await make_user(sessions, "pl3-new@railtech.uz", ["manager"])
    async with sessions() as session, session.begin():
        row = Client(name="ООО Почта")
        session.add(row)
        await session.flush()
        session.add(ClientContact(client_id=row.id, full_name="К", email="Buyer@Client.uz"))
        client_id = row.id
    response = client.post(
        "/api/v1/leads",
        json={"source": "email", "name": "Новый", "email": "buyer@client.uz"},
        headers=login(client, manager.email, password),
    )
    assert response.status_code == 409
    assert response.json()["details"] == {
        "reason": "client_exists",
        "client_id": client_id,
        "client_name": "ООО Почта",
        "field": "email",
    }


async def seed_client(
    sessions: async_sessionmaker[AsyncSession],
    name: str,
    *,
    phone: str | None = None,
    email: str | None = None,
    open_lead: bool = True,
) -> tuple[int, int | None]:
    async with sessions() as session, session.begin():
        row = Client(name=name)
        session.add(row)
        await session.flush()
        session.add(ClientContact(client_id=row.id, full_name="К", phone_e164=phone, email=email))
        lead_id = None
        if open_lead:
            lead = Lead(display_name=name, source="phone", stage="in_progress", client_id=row.id)
            session.add(lead)
            await session.flush()
            lead_id = lead.id
        return row.id, lead_id


async def lead_count(sessions: async_sessionmaker[AsyncSession]) -> int:
    async with sessions() as session:
        return len((await session.scalars(select(Lead.id))).all())


async def test_web_request_from_client_contact_attaches_to_open_lead(
    client: TestClient, sessions: async_sessionmaker[AsyncSession], live_settings: Settings
) -> None:
    _, lead_id = await seed_client(sessions, "ООО Клиент", email="buyer@client.uz")
    assert lead_id is not None
    got = post_web(client, live_settings, email="Buyer@Client.uz", phone=None, form="site-customer")
    assert got == lead_id
    assert await lead_count(sessions) == 1
    lead = await one_lead(sessions, lead_id)
    fact = lead.qualification["repeat_requests"][-1]
    assert (fact["kind"], fact["form"]) == ("client_contact", "site-customer")
    assert "possible_duplicates" not in lead.qualification
    async with sessions() as session:
        notes = (await session.scalars(select(LeadNote).where(LeadNote.lead_id == lead_id))).all()
    assert len(notes) == 1


async def test_web_request_from_client_contact_not_attached_when_not_exact(
    client: TestClient, sessions: async_sessionmaker[AsyncSession], live_settings: Settings
) -> None:
    # Other role (partner form): lead is created, possible duplicate recorded.
    cid, existing = await seed_client(sessions, "ООО Один", email="one@client.uz")
    partner = post_web(
        client, live_settings, email="one@client.uz", phone=None, form="site-partner"
    )
    assert partner != existing
    lead = await one_lead(sessions, partner)
    dup = lead.qualification["possible_duplicates"][-1]
    assert (dup["reason"], dup["client_ids"]) == ("other_role", [cid])

    # Client without an open lead: lead is created, suggestion recorded.
    cid2, _ = await seed_client(sessions, "ООО Два", email="two@client.uz", open_lead=False)
    created = post_web(client, live_settings, email="two@client.uz", phone=None)
    dup2 = (await one_lead(sessions, created)).qualification["possible_duplicates"][-1]
    assert (dup2["reason"], dup2["client_ids"]) == ("no_open_lead", [cid2])

    # Phone belongs to one client, e-mail to another: ambiguous, never attached.
    a, a_lead = await seed_client(sessions, "ООО А", phone="+998935550001")
    b, b_lead = await seed_client(sessions, "ООО Б", email="b@client.uz")
    mixed = post_web(client, live_settings, phone="+998935550001", email="b@client.uz")
    assert mixed not in (a_lead, b_lead)
    dup3 = (await one_lead(sessions, mixed)).qualification["possible_duplicates"][-1]
    assert (dup3["reason"], dup3["client_ids"]) == ("ambiguous", [a, b])
