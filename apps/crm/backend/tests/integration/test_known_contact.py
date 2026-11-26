"""КОНТР-1а: сообщение известного контакта компании — не новый лид (демо-данные, вымышленные)."""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.company_conversation import MARK_KEY
from app.models.auth import AuditLog
from app.models.clients import Client, ClientContact
from app.models.leads import Lead, Message, TelegramIdentity
from app.repositories import crm
from app.services import known_contact
from app.services.conversation import ConversationService, Incoming
from app.services.settings import SettingsService
from tests.integration.crm_helpers import make_user

pytestmark = pytest.mark.integration

TG = 9101
PHONE = "+998900000101"


def service(sessions: async_sessionmaker[AsyncSession]) -> ConversationService:
    return ConversationService(
        sessions,
        SettingsService(sessions, ttl_s=0),
        None,  # type: ignore[arg-type]
        b"k",
    )


async def company(
    sessions: async_sessionmaker[AsyncSession],
    name: str,
    *,
    owner: int | None,
    tg: int | None = None,
    phone: str | None = None,
) -> int:
    async with sessions() as session, session.begin():
        client = Client(name=name, owner_user_id=owner)
        session.add(client)
        await session.flush()
        identity_id = None
        if tg is not None:
            identity = TelegramIdentity(tg_user_id=tg)
            session.add(identity)
            await session.flush()
            identity_id = identity.id
        session.add(
            ClientContact(
                client_id=client.id,
                full_name="Демо Контакт",
                phone_e164=phone,
                telegram_identity_id=identity_id,
                is_primary=True,
            )
        )
        return client.id


async def write(sessions: async_sessionmaker[AsyncSession], tg: int = TG) -> None:
    inc = Incoming(tg_user_id=tg, chat_id=tg, text="/start", first_name="Демо", language_code="ru")
    await service(sessions).start(inc)


async def lead_of(sessions: async_sessionmaker[AsyncSession], tg: int = TG) -> Lead:
    async with sessions() as session:
        identity = (
            await session.scalars(select(TelegramIdentity).where(TelegramIdentity.tg_user_id == tg))
        ).one()
        lead = await session.get(Lead, identity.lead_id)
        assert lead is not None
        return lead


async def test_known_contact_goes_to_company_owner_not_to_new(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    owner, _ = await make_user(sessions, "owner@example.test", ["manager"])
    client_id = await company(sessions, "Демо Партнёр", owner=owner.id, tg=TG)
    await write(sessions)
    lead = await lead_of(sessions)
    assert lead.client_id == client_id
    assert lead.assigned_user_id == owner.id
    assert lead.stage != "new"
    assert lead.owner_mode == "bot"  # бот отвечает как прежде
    assert lead.company_name == "Демо Партнёр"
    assert MARK_KEY in lead.qualification
    async with sessions() as session:
        audited = (
            await session.scalars(select(AuditLog).where(AuditLog.action == "lead.known_contact"))
        ).all()
        _, mine, unassigned = await crm.inbox(session, owner.id)
    assert len(audited) == 1
    assert lead.id in [item.id for item in mine]
    assert lead.id not in [item.id for item in unassigned]


async def test_unknown_person_stays_a_new_lead(sessions: async_sessionmaker[AsyncSession]) -> None:
    owner, _ = await make_user(sessions, "owner@example.test", ["manager"])
    await company(sessions, "Демо Партнёр", owner=owner.id, tg=TG)
    await write(sessions, tg=9999)
    lead = await lead_of(sessions, tg=9999)
    assert (lead.stage, lead.assigned_user_id, lead.client_id) == ("new", None, None)
    assert MARK_KEY not in lead.qualification


async def test_company_without_owner_is_marked_but_stays_in_queue(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    client_id = await company(sessions, "Демо Партнёр", owner=None, tg=TG)
    await write(sessions)
    lead = await lead_of(sessions)
    assert (lead.client_id, lead.assigned_user_id, lead.stage) == (client_id, None, "new")
    assert lead.company_name == "Демо Партнёр"


async def test_contact_of_company_a_is_never_attached_to_company_b(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    owner, _ = await make_user(sessions, "owner@example.test", ["manager"])
    a = await company(sessions, "Демо А", owner=owner.id, tg=TG)
    b = await company(sessions, "Демо Б", owner=owner.id)
    await write(sessions)
    lead = await lead_of(sessions)
    assert lead.client_id == a
    async with sessions() as session, session.begin():
        row = await session.get(Lead, lead.id)
        assert row is not None
        row.client_id = b  # лид ошибочно привязан к другой компании
        row.assigned_user_id = None
        row.qualification = {}
        row.stage = "new"
        assert await known_contact.apply(session, row) is known_contact.Outcome.NONE
        assert row.client_id == b
        assert row.assigned_user_id is None


async def test_phone_shared_by_two_companies_is_not_guessed(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    owner, _ = await make_user(sessions, "owner@example.test", ["manager"])
    await company(sessions, "Демо А", owner=owner.id, phone=PHONE)
    await company(sessions, "Демо Б", owner=owner.id, phone=PHONE)
    await write(sessions)
    async with sessions() as session, session.begin():
        lead = await lead_of(sessions)
        row = await session.get(Lead, lead.id)
        assert row is not None
        row.phone_e164 = PHONE
        assert await known_contact.apply(session, row) is known_contact.Outcome.NONE
        assert row.client_id is None


async def test_lead_handled_by_a_person_is_untouched(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    owner, _ = await make_user(sessions, "owner@example.test", ["manager"])
    other, _ = await make_user(sessions, "other@example.test", ["manager"])
    await company(sessions, "Демо Партнёр", owner=owner.id, tg=TG)
    async with sessions() as session, session.begin():
        identity = TelegramIdentity(tg_user_id=TG + 1)
        session.add(identity)
        await session.flush()
        lead = Lead(owner_mode="human", assigned_user_id=other.id, stage="in_progress")
        session.add(lead)
        await session.flush()
        identity.lead_id = lead.id
        assert await known_contact.apply(session, lead) is known_contact.Outcome.NONE
        assert lead.assigned_user_id == other.id


async def test_backfill_applies_to_existing_lead_and_is_idempotent(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """Лид создан до правила: компания есть, лид в «Новых» — повторное применение его забирает."""
    owner, _ = await make_user(sessions, "owner@example.test", ["manager"])
    await write(sessions)  # контакта компании ещё нет → обычный лид
    lead = await lead_of(sessions)
    assert lead.stage == "new"
    client_id = await company(sessions, "Демо Партнёр", owner=owner.id)
    async with sessions() as session, session.begin():
        identity = (await session.scalars(select(TelegramIdentity))).one()
        contact = (await session.scalars(select(ClientContact))).one()
        contact.telegram_identity_id = identity.id
    async with sessions() as session, session.begin():
        row = await session.get(Lead, lead.id)
        assert row is not None
        assert await known_contact.apply(session, row) is known_contact.Outcome.ASSIGNED
    async with sessions() as session, session.begin():
        row = await session.get(Lead, lead.id)
        assert row is not None
        assert await known_contact.apply(session, row) is known_contact.Outcome.UNCHANGED
        assert (row.client_id, row.assigned_user_id) == (client_id, owner.id)
        assert row.stage == "engaged"
        messages = (await session.scalars(select(Message))).all()
        assert messages  # история беседы на месте


async def test_email_added_on_lead_reaches_the_company_contact(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """Почта, добавленная в карточке лида, попадает в контакт компании (и дальше — в ERP)."""
    from app.security.audit import Actor
    from app.services import lead_contact_sync

    owner, _ = await make_user(sessions, "owner@example.test", ["manager"])
    await company(sessions, "Демо Партнёр", owner=owner.id, tg=TG)
    await write(sessions)
    lead = await lead_of(sessions)
    async with sessions() as session, session.begin():
        row = await session.get(Lead, lead.id)
        assert row is not None
        row.email = "contact@example.test"
        assert await lead_contact_sync.sync_to_contact(session, row, {"email"}, Actor.system())
        assert not await lead_contact_sync.sync_to_contact(session, row, {"email"}, Actor.system())
        contact = (await session.scalars(select(ClientContact))).one()
        assert contact.email == "contact@example.test"


async def _two_contacts(sessions: async_sessionmaker[AsyncSession], q_email: str | None) -> int:
    """Компания: основной P (с почтой) и второй Q (по телефону); лид Q опознан по телефону."""
    owner, _ = await make_user(sessions, "owner@example.test", ["manager"])
    client_id = await company(sessions, "Демо Партнёр", owner=owner.id)
    async with sessions() as session, session.begin():
        p = (await session.scalars(select(ClientContact))).one()
        p.email = "p@example.test"
        session.add(
            ClientContact(
                client_id=client_id,
                full_name="Демо Второй",
                phone_e164=PHONE,
                email=q_email,
            )
        )
    await write(sessions)
    async with sessions() as session, session.begin():
        identity = (await session.scalars(select(TelegramIdentity))).one()
        identity.phone_e164 = PHONE
        lead = await session.get(Lead, identity.lead_id)
        assert lead is not None
        assert await known_contact.apply(session, lead) is known_contact.Outcome.ASSIGNED
        return lead.id


async def test_email_typed_for_second_contact_never_overwrites_the_primary(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    from app.security.audit import Actor
    from app.services import lead_contact_sync

    lead_id = await _two_contacts(sessions, q_email=None)
    async with sessions() as session, session.begin():
        lead = await session.get(Lead, lead_id)
        assert lead is not None
        lead.email = "q@example.test"
        assert await lead_contact_sync.sync_to_contact(session, lead, {"email"}, Actor.system())
        emails = {
            c.full_name: c.email for c in (await session.scalars(select(ClientContact))).all()
        }
    assert emails == {"Демо Контакт": "p@example.test", "Демо Второй": "q@example.test"}


async def test_existing_other_email_is_not_overwritten_and_lead_gets_a_note(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    from app.models.leads import LeadNote
    from app.security.audit import Actor
    from app.services import lead_contact_sync

    lead_id = await _two_contacts(sessions, q_email="old@example.test")
    async with sessions() as session, session.begin():
        lead = await session.get(Lead, lead_id)
        assert lead is not None
        lead.email = "q@example.test"
        assert not await lead_contact_sync.sync_to_contact(session, lead, {"email"}, Actor.system())
        emails = sorted(c.email or "" for c in (await session.scalars(select(ClientContact))).all())
        notes = (await session.scalars(select(LeadNote.text))).all()
    assert emails == ["old@example.test", "p@example.test"]
    assert notes == [lead_contact_sync.CONFLICT_NOTE]
