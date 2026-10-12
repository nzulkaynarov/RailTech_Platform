"""Путь лида через действия CRM: эскалация → «Забрать» → итог → клиент (аудит P-01, P-15)."""

from datetime import UTC, date, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.errors import ConflictError
from app.models.clients import Client, Document
from app.models.leads import Lead, TelegramIdentity
from app.models.qualification import Escalation
from app.security.principal import Principal
from app.services.clients import ClientService
from app.services.conversation import ConversationService, Incoming
from app.services.lead_messenger import LeadMessenger
from app.services.leads import LeadService
from app.services.settings import SettingsService
from tests.integration.crm_helpers import FakeSender, make_user
from tests.integration.test_customer import USER, msg, service
from tests.unit.agents.fakes import ReplayModel, reply

pytestmark = pytest.mark.integration
__all__ = ["service"]


async def escalated_prospect(
    sessions: async_sessionmaker[AsyncSession], svc: ConversationService
) -> int:
    """Лид прошёл согласие в боте и передан менеджеру (как после триггера эскалации)."""
    await svc.start(Incoming(tg_user_id=USER, chat_id=USER, text="/start", language_code="ru"))
    await svc.accept_consent(USER)
    async with sessions() as session, session.begin():
        lead = (await session.scalars(select(Lead))).one()
        lead.stage, lead.owner_mode = "handoff", "paused"
        session.add(Escalation(lead_id=lead.id, reason_codes=["human_requested"], priority="hot"))
        return lead.id


async def manager(sessions: async_sessionmaker[AsyncSession]) -> tuple[Principal, LeadService]:
    account, _ = await make_user(sessions, "dilshod@railtech.uz", ["manager"])
    who = Principal(account.id, "Дилшод Рахимов", ("manager",))
    leads = LeadService(
        sessions, SettingsService(sessions, ttl_s=0), LeadMessenger(sessions, FakeSender())
    )
    return who, leads


async def state(sessions: async_sessionmaker[AsyncSession], lead_id: int) -> tuple[str, str, str]:
    async with sessions() as session:
        lead = await session.get(Lead, lead_id)
        escalation = (await session.scalars(select(Escalation))).one()
        assert lead is not None
        return lead.stage, lead.owner_mode, escalation.status


@pytest.mark.parametrize("outcome", ["won", "lost"])
async def test_closing_the_deal_hands_dialog_back_to_bot(
    service: tuple[ConversationService, ReplayModel, list[str]],
    sessions: async_sessionmaker[AsyncSession],
    outcome: str,
) -> None:
    svc, _, _ = service
    lead_id = await escalated_prospect(sessions, svc)
    who, leads = await manager(sessions)

    await leads.take(who, lead_id)
    await leads.close(who, lead_id, outcome, None)  # type: ignore[arg-type]

    assert await state(sessions, lead_id) == (outcome, "bot", "closed")


async def test_customer_gets_documents_right_after_make_customer(
    service: tuple[ConversationService, ReplayModel, list[str]],
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    svc, model, _ = service
    lead_id = await escalated_prospect(sessions, svc)
    who, leads = await manager(sessions)
    await leads.take(who, lead_id)
    await leads.close(who, lead_id, "won", "договор подписан")

    client_id = await ClientService(sessions).make_customer(who, lead_id, None, "Альфа")
    async with sessions() as session, session.begin():
        session.add(
            Document(
                client_id=client_id,
                type="contract",
                title="Договор поставки №15",
                number="15",
                doc_date=date(2026, 7, 14),
                storage_key="k/1",
                filename="dogovor.pdf",
                mime="application/pdf",
                size_bytes=10,
            )
        )

    assert await state(sessions, lead_id) == ("customer", "bot", "closed")
    out = await svc.handle_message(msg("Пришлите договор, который мы заключали в июле"))
    assert model.requests == []
    assert out[-1].document is not None
    assert out[-1].document["filename"] == "dogovor.pdf"


async def test_make_customer_does_not_silently_move_telegram_to_another_client(
    service: tuple[ConversationService, ReplayModel, list[str]],
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    svc, _, _ = service
    lead_id = await escalated_prospect(sessions, svc)
    who, leads = await manager(sessions)
    await leads.take(who, lead_id)
    await leads.close(who, lead_id, "won", None)
    clients = ClientService(sessions)
    first = await clients.make_customer(who, lead_id, None, "Альфа")
    async with sessions() as session, session.begin():
        other = Client(name="Бета")
        session.add(other)
        await session.flush()
        other_id = other.id

    with pytest.raises(ConflictError):
        await clients.make_customer(who, lead_id, other_id, None)

    async with sessions() as session:
        identity = (await session.scalars(select(TelegramIdentity))).one()
        assert identity.client_id == first
        assert identity.verified_at is not None
        assert identity.verified_at <= datetime.now(UTC)


async def test_waiting_lead_is_acknowledged_without_model_once_per_interval(
    service: tuple[ConversationService, ReplayModel, list[str]],
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    svc, model, _ = service
    lead_id = await escalated_prospect(sessions, svc)
    async with sessions() as session, session.begin():
        lead = await session.get(Lead, lead_id)
        assert lead is not None
        lead.last_bot_msg_at = None  # передача была давно

    first = await svc.handle_message(msg("Ау, есть кто?"))
    second = await svc.handle_message(msg("Жду ответа"))

    assert [o.text for o in first] == ["Ваше сообщение передано менеджеру, он скоро ответит."]
    assert second == []
    assert model.requests == []
    # явная просьба позвать человека подтверждается всегда, даже внутри интервала
    pressed = await svc.handle_message(
        Incoming(tg_user_id=USER, chat_id=USER, text="Позвать менеджера", human_requested=True)
    )
    assert [o.text for o in pressed] == ["Ваше сообщение передано менеджеру, он скоро ответит."]


async def test_human_request_while_waiting_raises_priority(
    service: tuple[ConversationService, ReplayModel, list[str]],
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    svc, _, _ = service
    lead_id = await escalated_prospect(sessions, svc)
    async with sessions() as session, session.begin():
        escalation = (await session.scalars(select(Escalation))).one()
        escalation.priority, escalation.reason_codes = "info", ["attachment_received"]

    await svc.handle_message(
        Incoming(tg_user_id=USER, chat_id=USER, text="/human", human_requested=True)
    )

    async with sessions() as session:
        escalation = (await session.scalars(select(Escalation))).one()
        lead = await session.get(Lead, lead_id)
    assert escalation.priority == "hot"
    assert "human_requested" in escalation.reason_codes
    assert lead is not None
    assert lead.owner_mode == "paused"


async def test_lost_lead_who_returns_can_be_taken_again(
    service: tuple[ConversationService, ReplayModel, list[str]],
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    svc, model, _ = service
    lead_id = await escalated_prospect(sessions, svc)
    who, leads = await manager(sessions)
    await leads.take(who, lead_id)
    await leads.close(who, lead_id, "lost", "дорого")
    model.responses.append(reply("Здравствуйте! Чем помочь?"))

    await svc.handle_message(msg("Мы передумали, давайте обсудим"))
    async with sessions() as session:
        lead = await session.get(Lead, lead_id)
        assert lead is not None
        assert (lead.stage, lead.owner_mode) == ("engaged", "bot")

    await leads.take(who, lead_id)
    stage, owner_mode, _ = await state(sessions, lead_id)
    assert (stage, owner_mode) == ("in_progress", "human")
