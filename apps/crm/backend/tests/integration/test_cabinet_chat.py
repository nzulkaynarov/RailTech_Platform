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
from typing import Any, cast

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bus import events as bus_events
from app.bus import runtime
from app.bus.runtime import build_bus
from app.domain.language import Language
from app.models.clients import Client, ClientContact
from app.models.leads import Conversation, Lead, Message
from app.models.qualification import Escalation
from app.repositories import cabinet_chat as cabinet_repo
from app.repositories import leads as leads_repo
from app.security.principal import Principal
from app.services import cabinet_chat
from app.services.cabinet_chat import CabinetChatService, CabinetCompanyMismatchError
from app.services.conversation_erasure import ErasureMixin
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
    async with sessions() as session:
        envelope = await session.scalar(
            text("SELECT envelope FROM rt_bus_outbox WHERE type = :t"),
            {"t": bus_events.LEAD_CREATED},
        )
    # в перечне LeadSource v1 нет «cabinet»: веб-канал и точный источник отдельным полем
    assert (envelope["data"]["lead"]["source"], envelope["data"]["lead"]["source_detail"]) == (
        "web",
        "cabinet",
    )


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

    monkeypatch.setattr(bus_events, "cabinet_message_sent", publish_then_fail)
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


class Eraser(ErasureMixin):
    """Боевой путь /delete (`ErasureMixin.erase`) без бота: агент и уведомления — заглушки."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions
        self._settings = SettingsService(sessions)
        self._agent = cast(Any, SimpleNamespace(forget=self._forget_agent))
        self._erase_attachments = None

    async def _forget_agent(self, lead_id: int) -> None:
        return None

    async def language_of(self, tg_user_id: int) -> Language:
        return "ru"

    async def _fire(
        self, lead_id: int | None, escalation_id: int | None, escalated_lead: int | None = None
    ) -> None:
        return None


async def person_with_colleague(
    sessions: async_sessionmaker[AsyncSession], tg: int
) -> tuple[int, int, int, int]:
    """Клиент с лидом-человеком из Telegram (он же контакт А) и коллегой (контакт Б); в кабинете
    пишут оба, менеджер отвечает. Возвращает (клиент, лид, контакт А, контакт Б)."""
    lead_id = await escalated_lead(sessions, tg_user_id=tg)
    client_id = await make_client(sessions, owner=None, erp_company_id=COMPANY)
    async with sessions() as session, session.begin():
        lead = await session.get(Lead, lead_id)
        assert lead is not None
        lead.client_id = client_id
        identity = await leads_repo.get_identity(session, tg)
        assert identity is not None
        person = ClientContact(
            client_id=client_id, full_name="Азиз", telegram_identity_id=identity.id
        )
        colleague = ClientContact(client_id=client_id, full_name="Дилноза")
        session.add_all([person, colleague])
        await session.flush()
        ids = (person.id, colleague.id)
    service = service_of(sessions)
    for key, crm_contact, erp_contact, name in (
        ("key-person-01", ids[0], 310, "Азиз"),
        ("key-colleague", ids[1], 311, "Дилноза"),
    ):
        event = posted(key, crm_client_id=client_id, text_=f"Пишет {name}")
        event.data["payload"]["author"] = {
            "erp_contact_id": erp_contact,
            "crm_contact_id": crm_contact,
            "name": name,
        }
        await accept(sessions, service, event)
    return client_id, lead_id, ids[0], ids[1]


async def cabinet_texts(sessions: async_sessionmaker[AsyncSession]) -> dict[str, str]:
    async with sessions() as session:
        rows = await session.execute(
            select(Message.meta["client_message_id"].astext, Message.text)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(Conversation.channel == "cabinet", Message.role == "lead")
        )
        return {row[0]: row[1] for row in rows.all()}


async def test_delete_erases_only_the_persons_cabinet_messages_and_keeps_the_conversation(
    sessions: async_sessionmaker[AsyncSession], bus: Any
) -> None:
    """Боевой путь /delete: стирается только сообщение человека (контакт А); коллега (Б), ответ
    менеджера и беседа клиента остаются, якорь — новый лид клиента; ERP получает, чьё стереть."""
    sender = Sender()
    client_id, lead_id, _, _ = await person_with_colleague(sessions, 7301)
    account, _ = await make_user(sessions, "chat-erase@railtech.example", ["manager"])
    who = Principal(user_id=account.id, full_name="Илья Смирнов", roles=("manager",))
    leads = LeadService(sessions, SettingsService(sessions), LeadMessenger(sessions, sender))
    await leads.take(who, lead_id)
    await leads.reply(who, lead_id, "Ответ менеджера", client_message_id="reply-erase-1")

    await Eraser(sessions).erase(7301)

    texts = await cabinet_texts(sessions)
    assert texts["key-person-01"] == leads_repo.ERASED_TEXT
    assert texts["key-colleague"] == "Пишет Дилноза"
    (conversation,) = await cabinet_conversations(sessions)
    assert conversation.is_open
    assert conversation.client_id == client_id
    assert conversation.lead_id != lead_id
    async with sessions() as session:
        anchor = await session.get(Lead, conversation.lead_id)
        manager = await session.scalar(
            select(Message.text).where(
                Message.conversation_id == conversation.id, Message.role == "manager"
            )
        )
        erased_meta = await session.scalar(
            select(Message.meta).where(Message.meta["client_message_id"].astext == "key-person-01")
        )
        envelope = await session.scalar(
            text("SELECT envelope FROM rt_bus_outbox WHERE type = :t"),
            {"t": bus_events.LEAD_ERASED},
        )
    assert anchor is not None
    assert (anchor.erased_at, anchor.client_id, anchor.source) == (None, client_id, "cabinet")
    assert manager == "Ответ менеджера"
    assert erased_meta is not None
    assert erased_meta["erased"] is True
    assert "author_name" not in erased_meta
    assert envelope["data"]["cabinet"] == {
        "erp_company_id": COMPANY,
        "scope": "authors",
        "erp_contact_ids": [310],
    }


async def test_delete_moves_the_anchor_to_another_lead_of_the_client(
    sessions: async_sessionmaker[AsyncSession], bus: Any
) -> None:
    client_id, _, _, _ = await person_with_colleague(sessions, 7302)
    async with sessions() as session, session.begin():
        other = Lead(display_name="Другой лид клиента", client_id=client_id, stage="customer")
        session.add(other)
        await session.flush()
        other_id = other.id

    await Eraser(sessions).erase(7302)

    (conversation,) = await cabinet_conversations(sessions)
    assert conversation.lead_id == other_id


async def test_delete_of_a_lead_without_cabinet_messages_tells_erp_nothing_to_erase(
    sessions: async_sessionmaker[AsyncSession], bus: Any
) -> None:
    await escalated_lead(sessions, tg_user_id=7303)
    await Eraser(sessions).erase(7303)
    async with sessions() as session:
        envelope = await session.scalar(
            text("SELECT envelope FROM rt_bus_outbox WHERE type = :t"),
            {"t": bus_events.LEAD_ERASED},
        )
    assert "cabinet" not in envelope["data"]


async def test_a_client_conversation_of_another_erp_company_is_refused(
    sessions: async_sessionmaker[AsyncSession], bus: Any
) -> None:
    """Сопоставление разошлось: беседа клиента — компании 118, событие — о 999. В чужую ленту не
    пишем: обработка падает (событие уходит в failed журнала шины)."""
    client_id = await make_client(sessions, owner=None, erp_company_id=COMPANY)
    await accept(sessions, service_of(sessions), posted("key-0000001", crm_client_id=client_id))
    with pytest.raises(CabinetCompanyMismatchError):
        await accept(
            sessions,
            service_of(sessions),
            posted("key-0000002", crm_client_id=client_id, company=999),
        )
    assert sorted(await cabinet_texts(sessions)) == ["key-0000001"]


async def test_bot_history_is_telegram_only_and_assist_sees_both(
    sessions: async_sessionmaker[AsyncSession], bus: Any
) -> None:
    """Сообщения коллег контакта в кабинете не попадают в контекст модели в Telegram (бот,
    квалификатор, MCP); «Подсказать ответ» менеджеру видит обе беседы."""
    sender = Sender()
    _, _, lead_id, client_id = await taken(sessions, sender, 7304)
    await accept(
        sessions,
        service_of(sessions),
        posted("key-0000001", crm_client_id=client_id, text_="Из кабинета"),
    )
    async with sessions() as session:
        telegram = await leads_repo.recent_messages(session, lead_id, 20)
        both = await leads_repo.recent_messages(session, lead_id, 20, channel=None)
    assert "Из кабинета" not in [m.text for m in telegram]
    assert "Из кабинета" in [m.text for m in both]


async def cabinet_repo_channel(sessions: async_sessionmaker[AsyncSession], lead_id: int) -> Any:
    async with sessions() as session:
        return await cabinet_repo.last_inbound_channel(session, lead_id)
