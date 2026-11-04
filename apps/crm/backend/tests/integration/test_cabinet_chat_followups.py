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
from app.services.cabinet_erasure import SKIPPED_METRIC as SKIPPED
from tests.integration.test_cabinet_chat import (
    COMPANY,
    Eraser,
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
    """Другой лид клиента (станет якорем после /delete) со своей передачей в состоянии `status`."""
    async with sessions() as session, session.begin():
        other = Lead(display_name="Другой лид клиента", client_id=client_id, stage="customer")
        other.owner_mode = "human" if status == "taken" else "paused"
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


async def test_a_taken_handoff_of_the_new_anchor_does_not_hide_the_cabinet_message(
    sessions: async_sessionmaker[AsyncSession], bus: Any
) -> None:
    """У нового якоря передача уже у менеджера (taken): к ней не дописываем — «Требуют внимания»
    её не показывает; сообщение кабинета ждёт ответа отдельной открытой передачей."""
    client_id, _, _, _ = await person_with_colleague(sessions, 7406)
    other_id = await other_lead_with(sessions, client_id, "taken", timedelta(hours=2))

    await FiringEraser(sessions).erase(7406)

    (conversation,) = await cabinet_conversations(sessions)
    assert conversation.lead_id == other_id
    async with sessions() as session:
        escalated, _, _ = await crm_repo.inbox(session, me=0)
    assert other_id in {lead.id for lead in escalated}
    moved = await cabinet_escalation(sessions, other_id)
    assert moved is not None
    assert moved.status == "open"
    assert moved.reason_codes == ["cabinet_message"]


async def test_an_answered_conversation_moves_without_a_handoff(
    sessions: async_sessionmaker[AsyncSession], bus: Any
) -> None:
    """Передачи `cabinet_message` нет (ответили) — новому якорю ничего не переносится."""
    _, lead_id, _, _ = await person_with_colleague(sessions, 7402)
    async with sessions() as session, session.begin():
        await session.execute(
            text("UPDATE escalations SET status = 'closed' WHERE lead_id = :id"), {"id": lead_id}
        )
    await FiringEraser(sessions).erase(7402)
    (conversation,) = await cabinet_conversations(sessions)
    assert await cabinet_escalation(sessions, conversation.lead_id) is None


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
