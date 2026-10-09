"""Квалификатор на реальном Postgres: постобработка, журнал, эскалация, батчинг, таймер."""

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.qualifier.graph import QualifierAgent
from app.config import Settings
from app.main import create_app
from app.models.leads import Lead, Message
from app.models.qualification import Escalation, QualifierRun, StageTransition
from app.repositories import kb as kb_repo
from app.repositories import leads as repo
from app.services.lead_messenger import LeadMessenger
from app.services.qualifier import QualifierService
from app.services.settings import SettingsService
from app.services.timers import mark_unresponsive
from tests.integration.crm_helpers import login, make_user
from tests.unit.agents.fakes import ReplayModel, reply

pytestmark = pytest.mark.integration


class FakeSender:
    def __init__(self) -> None:
        self.sent: list[tuple[int, str]] = []

    async def send_message(self, chat_id: int, text: str) -> None:
        self.sent.append((chat_id, text))


def output(**overrides: Any) -> str:
    base: dict[str, Any] = {
        "need_summary": None,
        "product_interest": [],
        "intent": "info",
        "sentiment": "neutral",
        "qualification": {
            "budget_hint": None,
            "timeline": None,
            "decision_role": None,
            "company": None,
            "company_size": None,
            "region": None,
        },
        "proposed_stage": "engaged",
        "recommend_escalation": False,
        "escalation_reason": None,
        "confidence": 0.8,
        "next_best_action": "Ответить на вопрос",
    }
    return json.dumps({**base, **overrides}, ensure_ascii=False)


async def make_lead(sessions: async_sessionmaker[AsyncSession], stage: str = "new") -> int:
    async with sessions() as session, session.begin():
        await kb_repo.upsert_product(session, "pos-integration", "RT-POS Интеграция", None)
        lead, _, conversation = await repo.create_lead_with_identity(
            session,
            tg_user_id=9001,
            username=None,
            first_name="Азиз",
            chat_id=9001,
            language="ru",
            identity=None,
        )
        lead.consent_given_at = datetime.now(UTC)
        lead.stage = stage
        await repo.add_message(
            session,
            conversation_id=conversation.id,
            role="lead",
            text="Нужна интеграция 2 касс с 1С",
        )
        await repo.add_message(
            session,
            conversation_id=conversation.id,
            role="bot",
            text="Внедрение для одного магазина занимает 3–5 рабочих дней.",
            meta={"best_score": 0.8},
        )
        return lead.id


def service(
    sessions: async_sessionmaker[AsyncSession], *responses: str
) -> tuple[QualifierService, FakeSender]:
    sender = FakeSender()
    svc = QualifierService(
        sessions,
        SettingsService(sessions, ttl_s=0),
        QualifierAgent(ReplayModel(*(reply(r) for r in responses))),
        LeadMessenger(sessions, sender),
    )
    return svc, sender


async def load(sessions: async_sessionmaker[AsyncSession], lead_id: int) -> Lead:
    async with sessions() as session:
        lead = await repo.get_lead(session, lead_id)
        assert lead is not None
        return lead


async def test_new_lead_becomes_qualified_through_engaged(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    lead_id = await make_lead(sessions)
    svc, _ = service(
        sessions,
        output(
            need_summary="Интеграция двух касс с 1С",
            product_interest=["pos-integration", "invented-product"],
            proposed_stage="qualified",
            qualification={
                "budget_hint": None,
                "timeline": "<3m",
                "decision_role": "decision_maker",
                "company": "Ромашка",
                "company_size": None,
                "region": None,
            },
        ),
    )
    run_id = await svc.run(lead_id)
    lead = await load(sessions, lead_id)
    assert (lead.stage, lead.score) == ("handoff", 80)  # high_score → эскалация
    assert lead.product_interest == ["pos-integration"]
    assert lead.qualification["company"] == "Ромашка"
    async with sessions() as session:
        run = await session.get(QualifierRun, run_id)
        moves = (await session.scalars(select(StageTransition.to_stage))).all()
        escalation = (await session.scalars(select(Escalation))).one()
    assert run is not None
    assert (run.applied_stage, run.score_before, run.score_after) == ("qualified", 0, 80)
    assert run.triggers_fired == ["high_score"]
    assert list(moves) == ["engaged", "qualified", "handoff"]
    assert escalation.priority == "warm"


async def test_rejected_proposal_is_journaled(sessions: async_sessionmaker[AsyncSession]) -> None:
    lead_id = await make_lead(sessions, stage="qualified")
    svc, _ = service(sessions, output(proposed_stage="engaged"))
    run_id = await svc.run(lead_id)
    async with sessions() as session:
        run = await session.get(QualifierRun, run_id)
    assert run is not None
    assert run.applied_stage is None
    assert run.rejected_reason
    assert (await load(sessions, lead_id)).stage == "qualified"


async def test_contact_request_escalates_and_notifies_lead(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    lead_id = await make_lead(sessions, stage="engaged")
    svc, sender = service(sessions, output(intent="request_contact"))
    await svc.run(lead_id)
    lead = await load(sessions, lead_id)
    assert (lead.stage, lead.owner_mode) == ("handoff", "paused")
    assert len(sender.sent) == 1
    async with sessions() as session:
        escalation = (await session.scalars(select(Escalation))).one()
        last = (await session.scalars(select(Message).order_by(Message.id.desc()))).first()
    assert escalation.reason_codes == ["callback_requested"]
    assert escalation.sla_due_at is not None
    assert last is not None
    assert last.text == sender.sent[0][1]


async def test_repeated_trigger_does_not_duplicate_escalation(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    lead_id = await make_lead(sessions, stage="engaged")
    svc, sender = service(
        sessions, output(intent="request_contact"), output(intent="complaint", sentiment="negative")
    )
    await svc.run(lead_id)
    await svc.run(lead_id)
    async with sessions() as session:
        escalation = (await session.scalars(select(Escalation))).one()
    assert escalation.reason_codes == ["callback_requested", "negative_sentiment", "complaint"]
    assert len(sender.sent) == 1


async def test_model_failure_is_recorded(sessions: async_sessionmaker[AsyncSession]) -> None:
    lead_id = await make_lead(sessions)
    svc, _ = service(sessions, "not json", "still not json")
    run_id = await svc.run(lead_id)
    async with sessions() as session:
        run = await session.get(QualifierRun, run_id)
    assert run is not None
    assert run.error
    assert (await load(sessions, lead_id)).stage == "new"


async def test_enqueue_is_batched_by_queueing_lock(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    from app.tasks.qualify import enqueue_qualify
    from app.tasks.queue import queue

    async with queue.open_async():
        assert await enqueue_qualify(42) is True
        assert await enqueue_qualify(42) is False
        assert await enqueue_qualify(43) is True
        async with sessions() as session, session.begin():
            from sqlalchemy import text

            await session.execute(text("DELETE FROM procrastinate_jobs"))


async def test_timer_marks_silent_leads_unresponsive(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    lead_id = await make_lead(sessions, stage="engaged")
    now = datetime.now(UTC)

    async def silent_for(days: int) -> None:
        async with sessions() as session, session.begin():
            lead = await repo.get_lead(session, lead_id, for_update=True)
            assert lead is not None
            lead.last_lead_msg_at = now - timedelta(days=days)
            lead.last_bot_msg_at = now - timedelta(days=days) + timedelta(minutes=1)

    settings = SettingsService(sessions, ttl_s=0)
    await silent_for(4)  # BUSINESS §5: «Не отвечает» — 7 дней тишины
    assert await mark_unresponsive(sessions, settings, now) == 0
    await silent_for(8)
    assert await mark_unresponsive(sessions, settings, now) == 1
    assert await mark_unresponsive(sessions, settings, now) == 0
    lead = await load(sessions, lead_id)
    assert lead.stage == "unresponsive"
    assert lead.unresponsive_since is not None


async def test_decisions_feed(
    sessions: async_sessionmaker[AsyncSession], live_settings: Settings
) -> None:
    lead_id = await make_lead(sessions)
    svc, _ = service(sessions, output(proposed_stage="engaged"))
    await svc.run(lead_id)
    viewer, password = await make_user(sessions, "viewer@railtech.uz", ["viewer"])
    with TestClient(create_app(live_settings)) as client:
        assert client.get(f"/api/v1/leads/{lead_id}/decisions").status_code == 401
        headers = login(client, viewer.email, password)
        body = client.get(f"/api/v1/leads/{lead_id}/decisions", headers=headers).json()
        missing = client.get("/api/v1/leads/999999/decisions", headers=headers)
    assert missing.status_code == 404
    assert body["stage"] == "engaged"
    assert {i["kind"] for i in body["items"]} == {"qualifier", "transition"}
