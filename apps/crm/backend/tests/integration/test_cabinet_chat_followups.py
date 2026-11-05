"""CHAT-1b: хвосты ревью #399 — передача кабинета при стирании якоря, выгрузка диалогов без
кабинета, журнал пропущенного стирания.

* (g) неотвеченное сообщение кабинета не пропадает из «Требуют внимания» при `/delete` лида-якоря:
  передача `cabinet_message` переходит на новый якорь с исходным временем и сроком SLA, пост в
  канале команды — после коммита; боевой путь `ErasureMixin.erase`;
* (f) выгрузка диалогов для разметки и evals (`sample-dialogs`) берёт только беседу Telegram:
  сообщения коллег контакта из кабинета туда не попадают;
* (c) беседы кабинета двух компаний ERP у одного лида — стирание в ERP не публикуется, но не молча:
  лог-метрика `cabinet_erasure_skipped` с id, без ПД.
"""

import logging
import random
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bus import events as bus_events
from app.cli.sample_dialogs import sample
from app.models.leads import Conversation, Lead, Message
from app.models.qualification import Escalation
from app.repositories import crm as crm_repo
from app.repositories import leads as leads_repo
from app.security.principal import Principal
from app.services.cabinet_erasure import SKIPPED_METRIC as SKIPPED
from app.services.lead_messenger import LeadMessenger
from app.services.leads import LeadService
from app.services.settings import SettingsService
from tests.integration.crm_helpers import escalated_lead, make_user
from tests.integration.test_cabinet_chat import (
    COMPANY,
    Eraser,
    Sender,
    accept,
    bus,
    cabinet_conversations,
    make_client,
    person_with_colleague,
    posted,
    service_of,
)

pytestmark = pytest.mark.integration

__all__ = ["bus"]  # фикстура шины из соседнего файла


class FiringEraser(Eraser):
    """Как `Eraser`, но запоминает посты передач после коммита."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        super().__init__(sessions)
        self.fired: list[tuple[int | None, int | None, int | None]] = []

    async def _fire(
        self, lead_id: int | None, escalation_id: int | None, escalated_lead: int | None = None
    ) -> None:
        self.fired.append((lead_id, escalation_id, escalated_lead))


async def cabinet_escalation(
    sessions: async_sessionmaker[AsyncSession], lead_id: int
) -> Escalation | None:
    async with sessions() as session:
        found: Escalation | None = await session.scalar(
            select(Escalation).where(
                Escalation.lead_id == lead_id,
                Escalation.status.in_(("open", "snoozed", "taken")),
                Escalation.reason_codes.contains(["cabinet_message"]),
            )
        )
        return found


async def test_an_unanswered_cabinet_message_moves_with_the_conversation_on_delete(
    sessions: async_sessionmaker[AsyncSession], bus: Any
) -> None:
    """Лид-якорь ждёт ответа на сообщение коллеги из кабинета и стирается по /delete: передача
    `cabinet_message` уходит на новый якорь беседы с тем же временем и сроком, лид в «Требуют
    внимания», пост в канале команды — для перенесённой передачи."""
    _, lead_id, _, _ = await person_with_colleague(sessions, 7401)
    async with sessions() as session, session.begin():
        # передача открыта час назад, срок реакции — через полчаса (стенд передачи без SLA)
        await session.execute(
            text(
                "UPDATE escalations SET created_at = now() - interval '1 hour', "
                "sla_due_at = now() + interval '30 minutes', "
                "reason_text = 'Азиз просит скидку', recommendation = 'Позвонить Азизу' "
                "WHERE lead_id = :id"
            ),
            {"id": lead_id},
        )
    before = await cabinet_escalation(sessions, lead_id)
    assert before is not None
    created_at, sla_due_at = before.created_at, before.sla_due_at
    assert sla_due_at is not None
    eraser = FiringEraser(sessions)

    await eraser.erase(7401)

    (conversation,) = await cabinet_conversations(sessions)
    assert conversation.lead_id != lead_id
    moved = await cabinet_escalation(sessions, conversation.lead_id)
    assert moved is not None
    # причины Telegram стёртого лида и тексты записки (могут нести его ПД) — не переносятся
    assert moved.reason_codes == ["cabinet_message"]
    assert (moved.reason_text, moved.recommendation) == (None, None)
    assert moved.created_at == created_at
    assert moved.sla_due_at == sla_due_at
    async with sessions() as session:
        escalated, _, _ = await crm_repo.inbox(session, me=0)
        anchor = await session.get(Lead, conversation.lead_id)
        source = await session.get(Escalation, before.id)
    assert conversation.lead_id in {lead.id for lead in escalated}
    assert anchor is not None
    assert anchor.owner_mode == "paused"
    assert source is not None
    assert source.status == "closed"
    assert (None, moved.id, conversation.lead_id) in eraser.fired


async def other_lead_with(
    sessions: async_sessionmaker[AsyncSession], client_id: int, status: str, sla_in: timedelta
) -> int:
    """Другой лид клиента (станет якорем после /delete) со своей ждущей передачей `status`."""
    async with sessions() as session, session.begin():
        other = Lead(display_name="Другой лид клиента", client_id=client_id, stage="customer")
        other.owner_mode = "paused"  # передача от бота ждёт менеджера
        session.add(other)
        await session.flush()
        session.add(
            Escalation(
                lead_id=other.id,
                reason_codes=["human_requested"],
                priority="hot",
                status=status,
                sla_due_at=datetime.now(UTC) + sla_in,
            )
        )
        return other.id


async def set_sla(
    sessions: async_sessionmaker[AsyncSession], lead_id: int, sla_in: timedelta
) -> None:
    async with sessions() as session, session.begin():
        await session.execute(
            text("UPDATE escalations SET sla_due_at = :due WHERE lead_id = :id"),
            {"due": datetime.now(UTC) + sla_in, "id": lead_id},
        )


async def test_a_waiting_handoff_of_the_new_anchor_gets_the_cabinet_reason_and_the_earlier_sla(
    sessions: async_sessionmaker[AsyncSession], bus: Any
) -> None:
    """У нового якоря своя ждущая передача: одна запись в «Требуют внимания» — с причиной кабинета
    и более ранним сроком из двух."""
    client_id, lead_id, _, _ = await person_with_colleague(sessions, 7405)
    await set_sla(sessions, lead_id, timedelta(minutes=10))
    other_id = await other_lead_with(sessions, client_id, "open", timedelta(hours=2))

    await FiringEraser(sessions).erase(7405)

    (conversation,) = await cabinet_conversations(sessions)
    assert conversation.lead_id == other_id
    async with sessions() as session:
        escalated, _, _ = await crm_repo.inbox(session, me=0)
        rows = (
            await session.scalars(
                select(Escalation).where(
                    Escalation.lead_id == other_id, Escalation.status.in_(("open", "snoozed"))
                )
            )
        ).all()
    assert [lead.id for lead in escalated].count(other_id) == 1
    (row,) = rows
    assert row.reason_codes == ["human_requested", "cabinet_message"]
    assert row.sla_due_at is not None
    assert row.sla_due_at < datetime.now(UTC) + timedelta(minutes=11)


async def manager_takes(
    sessions: async_sessionmaker[AsyncSession], lead_id: int, email: str
) -> Principal:
    """Лида забирает настоящий менеджер («Забрать»): `human`, ответственный, передача `taken`."""
    account, _ = await make_user(sessions, email, ["manager"])
    who = Principal(user_id=account.id, full_name="Менеджер", roles=("manager",))
    service = LeadService(sessions, SettingsService(sessions), LeadMessenger(sessions, Sender()))
    await service.take(who, lead_id)
    return who


async def client_lead_in_telegram(
    sessions: async_sessionmaker[AsyncSession], client_id: int, tg: int
) -> int:
    """Ещё один лид клиента из Telegram с открытой передачей (станет якорем после /delete)."""
    other_id = await escalated_lead(sessions, tg_user_id=tg)
    async with sessions() as session, session.begin():
        other = await session.get(Lead, other_id)
        assert other is not None
        other.client_id = client_id
    return other_id


async def colleague_writes_again(
    sessions: async_sessionmaker[AsyncSession], client_id: int
) -> None:
    event = posted("key-colleague-2", crm_client_id=client_id, text_="Пишет Дилноза ещё раз")
    event.data["payload"]["author"] = {"erp_contact_id": 311, "crm_contact_id": None, "name": "Д"}
    await accept(sessions, service_of(sessions), event)


async def anchor_state(
    sessions: async_sessionmaker[AsyncSession], anchor_id: int, manager: Principal
) -> tuple[Lead, list[Escalation], list[int], list[int]]:
    async with sessions() as session:
        anchor = await session.get(Lead, anchor_id)
        assert anchor is not None
        rows = list(
            (await session.scalars(select(Escalation).where(Escalation.lead_id == anchor_id))).all()
        )
        escalated, mine, _ = await crm_repo.inbox(session, me=manager.user_id)
    return anchor, rows, [lead.id for lead in escalated], [lead.id for lead in mine]


async def test_an_anchor_held_by_a_manager_gets_the_message_in_mine_without_a_handoff(
    sessions: async_sessionmaker[AsyncSession], bus: Any
) -> None:
    """Новый якорь уже ведёт менеджер Б: передачу не заводим и не переназначаем — у Б лид «ждёт
    ответа» в «Мои» (как у входящего сообщения кабинета, когда беседа у человека). Иначе была бы
    открытая передача, которую Б не может закрыть («Забрать» своё — ничего не делает)."""
    client_id, _, _, _ = await person_with_colleague(sessions, 7406)
    other_id = await client_lead_in_telegram(sessions, client_id, 7416)
    manager_b = await manager_takes(sessions, other_id, "chat1b-b@railtech.example")
    await colleague_writes_again(sessions, client_id)

    await FiringEraser(sessions).erase(7406)

    (conversation,) = await cabinet_conversations(sessions)
    assert conversation.lead_id == other_id
    anchor, rows, escalated, mine = await anchor_state(sessions, other_id, manager_b)
    assert (anchor.owner_mode, anchor.assigned_user_id) == ("human", manager_b.user_id)
    assert [r.status for r in rows if r.status in ("open", "snoozed")] == []
    assert [r.status for r in rows].count("taken") == 1
    assert other_id not in escalated
    assert other_id in mine
    assert anchor.last_lead_msg_at is not None
    assert anchor.last_human_msg_at is None or anchor.last_lead_msg_at > anchor.last_human_msg_at


def service_for(sessions: async_sessionmaker[AsyncSession]) -> LeadService:
    return LeadService(sessions, SettingsService(sessions), LeadMessenger(sessions, Sender()))


async def waits_in_mine(sessions: async_sessionmaker[AsyncSession], lead_id: int) -> bool:
    """«Ждёт ответа» так, как её считает очередь «Мои» (`repositories/crm._waits_for_reply`)."""
    async with sessions() as session:
        lead = await session.get(Lead, lead_id)
    assert lead is not None
    if lead.owner_mode != "human" or lead.last_lead_msg_at is None:
        return False
    return lead.last_lead_msg_at > (lead.last_human_msg_at or lead.created_at)


async def test_an_anchor_manager_who_answered_his_own_lead_still_gets_the_cabinet_message(
    sessions: async_sessionmaker[AsyncSession], bus: Any
) -> None:
    """Ревью #403, сценарий 1: якорь ведёт менеджер Б и ответил своему лиду уже после сообщения
    кабинета. Отметка по времени сообщения не дала бы «ждёт ответа»; неотвеченность считается по
    беседе кабинета, поэтому сообщение в «Мои» у Б."""
    client_id, _, _, _ = await person_with_colleague(sessions, 7409)
    other_id = await client_lead_in_telegram(sessions, client_id, 7419)
    manager_b = await manager_takes(sessions, other_id, "chat1b-b3@railtech.example")
    await service_for(sessions).reply(manager_b, other_id, "Добрый день, Б на связи")
    async with sessions() as session:
        replied = await session.get(Lead, other_id)
    assert replied is not None
    assert replied.last_human_msg_at is not None
    assert not await waits_in_mine(sessions, other_id)

    await FiringEraser(sessions).erase(7409)

    (conversation,) = await cabinet_conversations(sessions)
    assert conversation.lead_id == other_id
    anchor, rows, escalated, mine = await anchor_state(sessions, other_id, manager_b)
    assert (anchor.owner_mode, anchor.assigned_user_id) == ("human", manager_b.user_id)
    assert [r for r in rows if r.status in ("open", "snoozed")] == []
    assert other_id not in escalated
    assert other_id in mine
    assert await waits_in_mine(sessions, other_id)


async def test_a_message_waiting_in_mine_of_the_erased_anchor_gets_a_handoff_at_the_new_one(
    sessions: async_sessionmaker[AsyncSession], bus: Any
) -> None:
    """Ревью #403, сценарий 2: стираемый якорь ведёт менеджер, передачи кабинета нет — сообщение
    ждало ответа в «Мои». После /delete новый якорь у бота: сообщение не пропадает, оно в «Требуют
    внимания» открытой передачей со сроком от настроек."""
    _, lead_id, _, _ = await person_with_colleague(sessions, 7410)
    async with sessions() as session, session.begin():
        await session.execute(
            text("UPDATE escalations SET status = 'closed' WHERE lead_id = :id"), {"id": lead_id}
        )
    manager = await manager_takes(sessions, lead_id, "chat1b-a3@railtech.example")
    await colleague_writes_again(sessions, await _client_of(sessions, lead_id))
    assert await cabinet_escalation(sessions, lead_id) is None
    assert await waits_in_mine(sessions, lead_id)
    eraser = FiringEraser(sessions)

    await eraser.erase(7410)

    (conversation,) = await cabinet_conversations(sessions)
    assert conversation.lead_id != lead_id
    anchor, rows, escalated, _ = await anchor_state(sessions, conversation.lead_id, manager)
    assert anchor.owner_mode == "paused"
    (row,) = rows
    assert (row.status, row.reason_codes) == ("open", ["cabinet_message"])
    assert row.sla_due_at is not None
    assert conversation.lead_id in escalated
    assert (None, row.id, conversation.lead_id) in eraser.fired


async def _client_of(sessions: async_sessionmaker[AsyncSession], lead_id: int) -> int:
    async with sessions() as session:
        lead = await session.get(Lead, lead_id)
    assert lead is not None
    assert lead.client_id is not None
    return lead.client_id


async def test_an_answered_conversation_moves_without_a_handoff(
    sessions: async_sessionmaker[AsyncSession], bus: Any
) -> None:
    """Менеджер забрал передачу и ответил в кабинет: передача остаётся `taken`, но беседа
    отвечена — новому якорю не переносится ни передача, ни «ждёт ответа». Отвеченность — по
    беседе, а не по тому, что у лида есть передача."""
    _, lead_id, _, _ = await person_with_colleague(sessions, 7411)
    manager = await manager_takes(sessions, lead_id, "chat1b-a4@railtech.example")
    await service_for(sessions).reply(manager, lead_id, "Ответ в кабинет")
    assert await cabinet_escalation(sessions, lead_id) is not None

    await FiringEraser(sessions).erase(7411)

    (conversation,) = await cabinet_conversations(sessions)
    assert conversation.lead_id != lead_id
    anchor, rows, escalated, _ = await anchor_state(sessions, conversation.lead_id, manager)
    assert rows == []
    assert conversation.lead_id not in escalated
    assert anchor.owner_mode == "bot"


async def test_both_handoffs_taken_leave_one_taken_and_keep_the_anchors_manager(
    sessions: async_sessionmaker[AsyncSession], bus: Any
) -> None:
    """Передачу стираемого лида забрал А, якорь ведёт Б: второй «забранной» нет, якорь у Б."""
    client_id, lead_id, _, _ = await person_with_colleague(sessions, 7407)
    await manager_takes(sessions, lead_id, "chat1b-a@railtech.example")
    other_id = await client_lead_in_telegram(sessions, client_id, 7417)
    manager_b = await manager_takes(sessions, other_id, "chat1b-b2@railtech.example")
    await colleague_writes_again(sessions, client_id)

    await FiringEraser(sessions).erase(7407)

    anchor, rows, _, mine = await anchor_state(sessions, other_id, manager_b)
    assert anchor.assigned_user_id == manager_b.user_id
    assert [r.status for r in rows].count("taken") == 1
    assert [r for r in rows if r.status in ("open", "snoozed")] == []
    assert other_id in mine


async def test_an_anchor_with_the_bot_gets_one_open_handoff(
    sessions: async_sessionmaker[AsyncSession], bus: Any
) -> None:
    """Якорь у бота: открытая передача кабинета, одна запись в «Требуют внимания»."""
    client_id, _, _, _ = await person_with_colleague(sessions, 7408)
    async with sessions() as session, session.begin():
        other = Lead(display_name="Лид клиента у бота", client_id=client_id, stage="customer")
        session.add(other)
        await session.flush()
        other_id = other.id

    await FiringEraser(sessions).erase(7408)

    (conversation,) = await cabinet_conversations(sessions)
    assert conversation.lead_id == other_id
    async with sessions() as session:
        escalated, _, _ = await crm_repo.inbox(session, me=0)
        anchor = await session.get(Lead, other_id)
    assert [lead.id for lead in escalated].count(other_id) == 1
    assert anchor is not None
    assert anchor.owner_mode == "paused"
    moved = await cabinet_escalation(sessions, other_id)
    assert moved is not None
    assert (moved.status, moved.reason_codes) == ("open", ["cabinet_message"])


async def test_sample_dialogs_for_evals_take_the_telegram_conversation_only(
    sessions: async_sessionmaker[AsyncSession], bus: Any
) -> None:
    """Переписка кабинета (сообщения коллег контакта) — не в выгрузке для разметки и evals."""
    _, lead_id, _, _ = await person_with_colleague(sessions, 7403)
    async with sessions() as session, session.begin():
        telegram = await leads_repo.open_conversation(session, lead_id)
        assert telegram is not None
        await leads_repo.add_message(
            session, conversation_id=telegram.id, role="bot", text="Ответ бота в Telegram"
        )

    async with sessions() as session:
        items = await sample(
            session,
            datetime.now(UTC) - timedelta(days=7),
            20,
            random.Random(1),  # noqa: S311 — выборка для разметки, не криптография
            "https://crm.example",
        )

    (item,) = [i for i in items if i["lead_id"] == lead_id]
    texts = [turn["text"] for turn in item["dialog"]]
    assert "Ответ бота в Telegram" in texts
    assert not [t for t in texts if t.startswith("Пишет ")]  # сообщения кабинета не выгружены


async def test_sample_dialogs_skip_a_lead_with_only_a_cabinet_conversation(
    sessions: async_sessionmaker[AsyncSession], bus: Any
) -> None:
    client_id = await make_client(sessions, owner=None, erp_company_id=COMPANY)
    await accept(sessions, service_of(sessions), posted("key-0000001", crm_client_id=client_id))
    async with sessions() as session, session.begin():
        (conversation,) = (
            await session.scalars(select(Conversation).where(Conversation.channel == "cabinet"))
        ).all()
        await session.execute(
            text(
                "INSERT INTO messages (conversation_id, role, text) VALUES (:c, 'bot', 'служебное')"
            ),
            {"c": conversation.id},
        )
    async with sessions() as session:
        items = await sample(
            session,
            datetime.now(UTC) - timedelta(days=7),
            20,
            random.Random(1),  # noqa: S311 — выборка для разметки, не криптография
            "https://crm.example",
        )
    assert items == []


async def test_erasure_across_two_erp_companies_is_logged_not_silent(
    sessions: async_sessionmaker[AsyncSession], bus: Any, caplog: pytest.LogCaptureFixture
) -> None:
    """Лид — автор в беседах кабинета двух компаний ERP: в одном событии одна компания, поэтому
    стирание в ERP не публикуется — но с лог-метрикой и id для разбора (ПД в журнале нет)."""
    _, lead_id, person, _ = await person_with_colleague(sessions, 7404)
    other_client = await make_client(sessions, owner=None, erp_company_id=COMPANY + 1)
    async with sessions() as session, session.begin():
        second = Conversation(
            lead_id=lead_id, channel="cabinet", client_id=other_client, erp_company_id=COMPANY + 1
        )
        session.add(second)
        await session.flush()
        session.add(
            Message(
                conversation_id=second.id,
                role="lead",
                text="Пишет Азиз во второй компании",
                meta={"channel": "cabinet", "crm_contact_id": person, "erp_contact_id": 410},
            )
        )

    caplog.set_level(logging.WARNING)
    await FiringEraser(sessions).erase(7404)

    skipped = [
        r.msg for r in caplog.records if isinstance(r.msg, dict) and r.msg.get("event") == SKIPPED
    ]
    assert len(skipped) == 1
    entry = skipped[0]
    assert entry["metric"] == SKIPPED
    assert entry["count"] == 1
    assert entry["lead_id"] == lead_id
    assert entry["erp_company_ids"] == [COMPANY, COMPANY + 1]
    assert "Азиз" not in repr(entry)
    async with sessions() as session:
        envelope = await session.scalar(
            text("SELECT envelope FROM rt_bus_outbox WHERE type = :t"),
            {"t": bus_events.LEAD_ERASED},
        )
    assert "cabinet" not in envelope["data"]
