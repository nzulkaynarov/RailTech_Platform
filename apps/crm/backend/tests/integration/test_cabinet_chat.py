"""CHAT-1 (ADR-0023): чат кабинета — беседа `cabinet` в очереди «Сообщения».

Входящее из кабинета (`erp.cabinet.message_posted`): одна беседа на клиента, якорный лид, клиент не
найден — сообщение не теряется, бот-ИИ не отвечает (эскалация `cabinet_message` или «Мои»), повтор
не задваивается. Ответ менеджера — в канал последнего входящего (кабинет или Telegram), сообщение и
`crm.cabinet.message_sent` одной транзакцией. Обезличивание лида беседы — `lead.erased` с компанией.
"""

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bus import events as bus_events
from app.bus import runtime
from app.bus.runtime import build_bus
from app.models.clients import Client
from app.models.leads import Conversation, Lead, Message
from app.models.qualification import Escalation
from app.repositories import cabinet_chat as cabinet_repo
from app.repositories import leads as leads_repo
from app.security.audit import Actor
from app.security.principal import Principal
from app.services import cabinet_chat
from app.services.cabinet_chat import CabinetChatService
from app.services.lead_messenger import LeadMessenger
from app.services.leads import LeadService
from app.services.settings import SettingsService
from tests.integration.crm_helpers import escalated_lead, make_user

pytestmark = pytest.mark.integration

COMPANY = 118


@pytest.fixture
def bus(sessions: async_sessionmaker[AsyncSession]) -> Iterator[Any]:
    stand = build_bus(sessions, None)
    runtime.set_bus(stand)
    yield stand
    runtime.set_bus(None)


class Sender:
    def __init__(self) -> None:
        self.sent: list[tuple[int, str]] = []

    async def send_message(self, chat_id: int, text: str, **_: Any) -> Any:
        self.sent.append((chat_id, text))
        return SimpleNamespace(message_id=700 + len(self.sent))


def posted(
    key: str,
    *,
    crm_client_id: int | None,
    company: int = COMPANY,
    text_: str = "Когда будет счёт?",
    context: dict[str, Any] | None = None,
) -> SimpleNamespace:
    payload: dict[str, Any] = {
        "erp_message_id": 1,
        "client_message_id": key,
        "author": {"erp_contact_id": 310, "crm_contact_id": None, "name": "Анна Петрова"},
        "company_name": "ООО «Пример»",
        "text": text_,
        "posted_at": "2026-11-04T07:40:00Z",
    }
    if context is not None:
        payload["context"] = context
    data = {
        "erp_company_id": company,
        "crm_client_id": crm_client_id,
        "actor": {"type": "client", "name": "Анна Петрова"},
        "payload": payload,
    }
    return SimpleNamespace(id=str(uuid.uuid4()), data=data)


async def accept(
    sessions: async_sessionmaker[AsyncSession], service: CabinetChatService, event: Any
) -> None:
    async with sessions() as session, session.begin():
        await service.accept(session, event)


async def make_client(
    sessions: async_sessionmaker[AsyncSession], *, owner: int | None, erp_company_id: int | None
) -> int:
    async with sessions() as session, session.begin():
        client = Client(name="ООО «Пример»", owner_user_id=owner, erp_company_id=erp_company_id)
        session.add(client)
        await session.flush()
        return client.id


async def cabinet_conversations(sessions: async_sessionmaker[AsyncSession]) -> list[Conversation]:
    async with sessions() as session:
        rows = await session.scalars(select(Conversation).where(Conversation.channel == "cabinet"))
        return list(rows)


async def outbox_count(sessions: async_sessionmaker[AsyncSession], event_type: str) -> int:
    async with sessions() as session:
        value = await session.scalar(
            text("SELECT count(*) FROM rt_bus_outbox WHERE type = :t"), {"t": event_type}
        )
    return int(value or 0)


def service_of(sessions: async_sessionmaker[AsyncSession]) -> CabinetChatService:
    return CabinetChatService(SettingsService(sessions), None)


async def test_one_cabinet_conversation_per_client_and_repeats_do_not_duplicate(
    sessions: async_sessionmaker[AsyncSession], bus: Any
) -> None:
    owner, _ = await make_user(sessions, "chat-owner@railtech.example", ["manager"])
    client_id = await make_client(sessions, owner=owner.id, erp_company_id=COMPANY)
    service = service_of(sessions)
    first = posted("key-0000001", crm_client_id=client_id)
    await accept(sessions, service, first)
    await accept(sessions, service, posted("key-0000002", crm_client_id=client_id))
    # то же сообщение, опубликованное заново (новый id события): второй записи нет
    await accept(sessions, service, posted("key-0000001", crm_client_id=client_id))

    (conversation,) = await cabinet_conversations(sessions)
    assert conversation.client_id == client_id
    assert conversation.erp_company_id == COMPANY
    assert conversation.tg_chat_id is None
    async with sessions() as session:
        keys = (
            await session.scalars(
                select(Message.meta["client_message_id"].astext).where(
                    Message.conversation_id == conversation.id
                )
            )
        ).all()
    assert sorted(keys) == ["key-0000001", "key-0000002"]


async def test_the_unique_index_refuses_a_second_cabinet_conversation_of_a_client(
    sessions: async_sessionmaker[AsyncSession], bus: Any
) -> None:
    client_id = await make_client(sessions, owner=None, erp_company_id=COMPANY)
    await accept(sessions, service_of(sessions), posted("key-0000001", crm_client_id=client_id))
    (conversation,) = await cabinet_conversations(sessions)
    with pytest.raises(IntegrityError):
        async with sessions() as session, session.begin():
            session.add(
                Conversation(lead_id=conversation.lead_id, channel="cabinet", client_id=client_id)
            )


async def test_anchor_is_the_lead_of_the_client_with_the_latest_activity(
    sessions: async_sessionmaker[AsyncSession], bus: Any
) -> None:
    client_id = await make_client(sessions, owner=None, erp_company_id=COMPANY)
    now = datetime.now(UTC)
    async with sessions() as session, session.begin():
        old = Lead(display_name="Старый", client_id=client_id, stage="customer")
        old.last_lead_msg_at = now - timedelta(days=30)
        fresh = Lead(display_name="Свежий", client_id=client_id, stage="customer")
        fresh.last_lead_msg_at = now - timedelta(hours=1)
        silent = Lead(display_name="Без сообщений", client_id=client_id, stage="customer")
        session.add_all([old, fresh, silent])
        await session.flush()
        fresh_id = fresh.id

    await accept(sessions, service_of(sessions), posted("key-0000001", crm_client_id=client_id))

    (conversation,) = await cabinet_conversations(sessions)
    assert conversation.lead_id == fresh_id
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(Lead)) == 3


async def test_without_a_lead_the_client_gets_a_cabinet_lead_of_its_owner(
    sessions: async_sessionmaker[AsyncSession], bus: Any
) -> None:
    owner, _ = await make_user(sessions, "chat-owner2@railtech.example", ["manager"])
    client_id = await make_client(sessions, owner=owner.id, erp_company_id=None)
    # клиент найден по сопоставлению ERP (crm_client_id), а не по erp_company_id
    await accept(sessions, service_of(sessions), posted("key-0000001", crm_client_id=client_id))

    (conversation,) = await cabinet_conversations(sessions)
    async with sessions() as session:
        lead = await session.get(Lead, conversation.lead_id)
    assert lead is not None
    assert (lead.source, lead.stage) == ("cabinet", "customer")
    assert lead.client_id == client_id
    assert lead.assigned_user_id == owner.id
    assert await outbox_count(sessions, bus_events.LEAD_CREATED) == 1


async def test_unknown_company_keeps_the_message_and_is_adopted_by_the_client_later(
    sessions: async_sessionmaker[AsyncSession], bus: Any
) -> None:
    service = service_of(sessions)
    await accept(sessions, service, posted("key-0000001", crm_client_id=None))

    (orphan,) = await cabinet_conversations(sessions)
    assert orphan.client_id is None
    assert orphan.erp_company_id == COMPANY
    async with sessions() as session:
        lead = await session.get(Lead, orphan.lead_id)
        assert lead is not None
        # новый лид без клиента сразу передан человеку: стадия «передан» (handoff)
        assert (lead.source, lead.stage, lead.client_id) == ("cabinet", "handoff", None)
        assert lead.display_name == "ООО «Пример»"
        escalation = await session.scalar(select(Escalation).where(Escalation.lead_id == lead.id))
    assert escalation is not None
    assert escalation.reason_codes == ["cabinet_message"]

    client_id = await make_client(sessions, owner=None, erp_company_id=COMPANY)
    await accept(sessions, service, posted("key-0000002", crm_client_id=None))

    (conversation,) = await cabinet_conversations(sessions)
    assert conversation.id == orphan.id
    assert conversation.client_id == client_id
    async with sessions() as session:
        adopted = await session.get(Lead, orphan.lead_id)
    assert adopted is not None
    assert adopted.client_id == client_id


async def test_the_bot_does_not_answer_and_the_message_is_escalated_with_sla(
    sessions: async_sessionmaker[AsyncSession], bus: Any
) -> None:
    client_id = await make_client(sessions, owner=None, erp_company_id=COMPANY)
    calls: list[tuple[int, bool]] = []

    async def hook(escalation_id: int, is_new: bool) -> None:
        calls.append((escalation_id, is_new))

    service = CabinetChatService(SettingsService(sessions), hook)
    event = posted("key-0000001", crm_client_id=client_id)
    await accept(sessions, service, event)
    await service.dispatch(event.id)

    (conversation,) = await cabinet_conversations(sessions)
    async with sessions() as session:
        roles = (
            await session.scalars(
                select(Message.role).where(Message.conversation_id == conversation.id)
            )
        ).all()
        escalation = await session.scalar(
            select(Escalation).where(Escalation.lead_id == conversation.lead_id)
        )
        lead = await session.get(Lead, conversation.lead_id)
    assert roles == ["lead"]  # ни ответа бота, ни «менеджер скоро ответит»
    assert escalation is not None
    assert escalation.reason_codes == ["cabinet_message"]
    assert escalation.status == "open"
    assert escalation.sla_due_at is not None
    assert lead is not None
    assert lead.owner_mode == "paused"
    assert calls == [(escalation.id, True)]


async def test_a_conversation_with_a_human_goes_to_mine_without_an_escalation(
    sessions: async_sessionmaker[AsyncSession], bus: Any
) -> None:
    owner, _ = await make_user(sessions, "chat-owner3@railtech.example", ["manager"])
    client_id = await make_client(sessions, owner=owner.id, erp_company_id=COMPANY)
    async with sessions() as session, session.begin():
        lead = Lead(display_name="Ведёт менеджер", client_id=client_id, stage="customer")
        lead.owner_mode, lead.assigned_user_id = "human", owner.id
        lead.last_human_msg_at = datetime.now(UTC) - timedelta(minutes=5)
        session.add(lead)
        await session.flush()
        lead_id = lead.id

    await accept(sessions, service_of(sessions), posted("key-0000001", crm_client_id=client_id))

    async with sessions() as session:
        escalations = await session.scalar(select(func.count()).select_from(Escalation))
        lead_after = await session.get(Lead, lead_id)
    assert escalations == 0
    assert lead_after is not None
    assert lead_after.last_lead_msg_at is not None
    assert lead_after.last_human_msg_at is not None
    assert lead_after.last_lead_msg_at > lead_after.last_human_msg_at  # «ждёт ответа» в «Мои»


async def taken(
    sessions: async_sessionmaker[AsyncSession], sender: Sender, tg: int
) -> tuple[LeadService, Principal, int, int]:
    """Лид из Telegram, забранный менеджером, и клиент с этой компанией ERP."""
    lead_id = await escalated_lead(sessions, tg_user_id=tg)
    account, _ = await make_user(sessions, f"chat-{tg}@railtech.example", ["manager"])
    who = Principal(user_id=account.id, full_name="Илья Смирнов", roles=("manager",))
    service = LeadService(sessions, SettingsService(sessions), LeadMessenger(sessions, sender))
    await service.take(who, lead_id)
    client_id = await make_client(sessions, owner=account.id, erp_company_id=COMPANY)
    async with sessions() as session, session.begin():
        lead = await session.get(Lead, lead_id)
        assert lead is not None
        lead.client_id = client_id
    sender.sent.clear()
    return service, who, lead_id, client_id


async def test_the_reply_goes_to_the_cabinet_when_the_client_last_wrote_there(
    sessions: async_sessionmaker[AsyncSession], bus: Any
) -> None:
    sender = Sender()
    service, who, lead_id, client_id = await taken(sessions, sender, 7101)
    await accept(sessions, service_of(sessions), posted("key-0000001", crm_client_id=client_id))
    assert await cabinet_repo_channel(sessions, lead_id) == "cabinet"

    message_id = await service.reply(who, lead_id, "Счёт сегодня", client_message_id="reply-00001")
    again = await service.reply(who, lead_id, "Счёт сегодня", client_message_id="reply-00001")

    assert again == message_id
    assert sender.sent == []  # не в Telegram
    assert await outbox_count(sessions, bus_events.CABINET_MESSAGE_SENT) == 1
    async with sessions() as session:
        envelope = await session.scalar(
            text("SELECT envelope FROM rt_bus_outbox WHERE type = :t"),
            {"t": bus_events.CABINET_MESSAGE_SENT},
        )
        message = await session.get(Message, message_id)
    assert envelope["data"]["text"] == "Счёт сегодня"
    assert envelope["data"]["erp_company_id"] == COMPANY
    assert envelope["data"]["manager_name"]
    assert message is not None
    assert message.meta["channel"] == "cabinet"


async def test_the_reply_goes_to_telegram_when_the_client_last_wrote_there(
    sessions: async_sessionmaker[AsyncSession], bus: Any
) -> None:
    sender = Sender()
    service, who, lead_id, client_id = await taken(sessions, sender, 7102)
    await accept(sessions, service_of(sessions), posted("key-0000001", crm_client_id=client_id))
    async with sessions() as session, session.begin():
        telegram = await leads_repo.open_conversation(session, lead_id)
        assert telegram is not None
        await leads_repo.add_message(
            session, conversation_id=telegram.id, role="lead", text="Я в Telegram"
        )
    assert await cabinet_repo_channel(sessions, lead_id) == "telegram"

    await service.reply(who, lead_id, "Отвечаю в Telegram", client_message_id="reply-00002")

    assert sender.sent == [(7102, "Отвечаю в Telegram")]
    assert await outbox_count(sessions, bus_events.CABINET_MESSAGE_SENT) == 0


async def test_a_failed_reply_publishes_nothing_and_keeps_no_message(
    sessions: async_sessionmaker[AsyncSession], bus: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    sender = Sender()
    _, who, lead_id, client_id = await taken(sessions, sender, 7103)
    await accept(sessions, service_of(sessions), posted("key-0000001", crm_client_id=client_id))
    original = bus_events.cabinet_message_sent

    async def publish_then_fail(*args: Any, **kwargs: Any) -> None:
        await original(*args, **kwargs)
        raise RuntimeError("after publish")

    monkeypatch.setattr(cabinet_chat.bus_events, "cabinet_message_sent", publish_then_fail)
    with pytest.raises(RuntimeError):
        await cabinet_chat.send_reply(
            sessions, lead_id, "Не уйдёт", "reply-00003", sent_by_user_id=who.user_id
        )

    assert await outbox_count(sessions, bus_events.CABINET_MESSAGE_SENT) == 0
    async with sessions() as session:
        managers = await session.scalar(
            select(func.count()).select_from(Message).where(Message.text == "Не уйдёт")
        )
    assert managers == 0


async def test_erasing_the_anchor_lead_tells_erp_and_the_next_message_gets_a_new_anchor(
    sessions: async_sessionmaker[AsyncSession], bus: Any
) -> None:
    client_id = await make_client(sessions, owner=None, erp_company_id=COMPANY)
    service = service_of(sessions)
    await accept(sessions, service, posted("key-0000001", crm_client_id=client_id))
    (conversation,) = await cabinet_conversations(sessions)
    async with sessions() as session, session.begin():
        lead = await session.get(Lead, conversation.lead_id)
        assert lead is not None
        company = await cabinet_repo.lead_cabinet_company(session, lead.id)
        await leads_repo.erase_lead(session, lead, datetime.now(UTC))
        await bus_events.lead_erased(
            session, lead, Actor(None, "bot"), cabinet_erp_company_id=company
        )
        erased_id = lead.id
    async with sessions() as session:
        envelope = await session.scalar(
            text("SELECT envelope FROM rt_bus_outbox WHERE type = :t"),
            {"t": bus_events.LEAD_ERASED},
        )
    assert envelope["data"]["cabinet_erp_company_id"] == COMPANY

    await accept(sessions, service, posted("key-0000002", crm_client_id=client_id))

    (after,) = await cabinet_conversations(sessions)
    assert after.id == conversation.id
    assert after.lead_id != erased_id
    assert after.is_open


async def cabinet_repo_channel(sessions: async_sessionmaker[AsyncSession], lead_id: int) -> Any:
    async with sessions() as session:
        return await cabinet_repo.last_inbound_channel(session, lead_id)
