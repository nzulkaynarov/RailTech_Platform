"""Действия над лидом, пост в канале, кнопка «Забрать», события SSE (Фаза 4)."""

import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.main import create_app
from app.models.leads import Lead, LeadNote, Message
from app.models.qualification import Escalation
from app.repositories import events
from app.services.event_broker import EventBroker
from app.services.lead_messenger import LeadMessenger
from app.services.notifications import NotificationService
from app.services.settings import SettingsService
from tests.integration.crm_helpers import FakeSender, escalated_lead, login, make_user

pytestmark = pytest.mark.integration


@pytest.fixture
def sender() -> FakeSender:
    return FakeSender()


@pytest.fixture
def client(
    sessions: async_sessionmaker[AsyncSession], live_settings: Settings, sender: FakeSender
) -> Iterator[TestClient]:
    app = create_app(live_settings)
    with TestClient(app) as test_client:
        container = app.state.container
        container.__dict__["lead_messenger"] = LeadMessenger(sessions, sender)
        container.__dict__.pop("lead_service", None)
        yield test_client


async def load(sessions: async_sessionmaker[AsyncSession], lead_id: int) -> tuple[Lead, Escalation]:
    async with sessions() as session:
        lead = await session.get(Lead, lead_id)
        escalation = (await session.scalars(select(Escalation))).one()
        assert lead is not None
        return lead, escalation


async def test_take_reply_return_with_note(
    client: TestClient, sessions: async_sessionmaker[AsyncSession], sender: FakeSender
) -> None:
    lead_id = await escalated_lead(sessions)
    manager, password = await make_user(sessions, "dilshod@railtech.uz", ["manager"])
    other, _ = await make_user(sessions, "other@railtech.uz", ["manager"])
    me = login(client, manager.email, password)
    them = login(client, other.email, password)

    assert client.post(f"/api/v1/leads/{lead_id}/actions/take", headers=me).status_code == 200
    lead, escalation = await load(sessions, lead_id)
    assert (lead.stage, lead.owner_mode, lead.assigned_user_id) == (
        "in_progress",
        "human",
        manager.id,
    )
    assert (escalation.status, escalation.taken_by_user_id) == ("taken", manager.id)
    assert "dilshod" in sender.sent[-1][1]
    card = client.get(f"/api/v1/leads/{lead_id}", headers=them).json()
    assert card["assigned_user_name"] == "dilshod"  # «кто ведёт» виден и не-админу

    assert client.post(f"/api/v1/leads/{lead_id}/actions/take", headers=them).status_code == 409
    foreign = client.post(f"/api/v1/leads/{lead_id}/messages", json={"text": "x"}, headers=them)
    assert foreign.status_code == 403

    sent = client.post(
        f"/api/v1/leads/{lead_id}/messages", json={"text": "Добрый день!"}, headers=me
    )
    assert sent.status_code == 200
    async with sessions() as session:
        message = await session.get(Message, sent.json()["id"])
    assert message is not None
    assert (message.role, message.sent_by_user_id) == ("manager", manager.id)

    back = client.post(
        f"/api/v1/leads/{lead_id}/actions/return_to_bot",
        json={"note": "Клиенту нужна 1С 8.3, считать 3 кассы"},
        headers=me,
    )
    assert back.status_code == 200
    lead, escalation = await load(sessions, lead_id)
    assert (lead.owner_mode, lead.stage) == ("bot", "engaged")
    assert escalation.status == "returned"
    async with sessions() as session:
        note = (await session.scalars(select(LeadNote))).one()
    assert note.visible_to_bot


async def test_close_won_requires_take(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    lead_id = await escalated_lead(sessions)
    manager, password = await make_user(sessions, "won@railtech.uz", ["manager"])
    headers = login(client, manager.email, password)
    early = client.post(f"/api/v1/leads/{lead_id}/actions/close_won", json={}, headers=headers)
    assert early.status_code == 409
    client.post(f"/api/v1/leads/{lead_id}/actions/take", headers=headers)
    won = client.post(
        f"/api/v1/leads/{lead_id}/actions/close_won", json={"reason": "договор"}, headers=headers
    )
    assert won.status_code == 200
    lead, escalation = await load(sessions, lead_id)
    assert lead.stage == "won"
    assert (escalation.status, escalation.outcome) == ("closed", "won")


async def test_snooze_and_inbox(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    lead_id = await escalated_lead(sessions)
    manager, password = await make_user(sessions, "snz@railtech.uz", ["manager"])
    headers = login(client, manager.email, password)
    inbox = client.get("/api/v1/inbox", headers=headers).json()
    assert [lead["id"] for lead in inbox["escalations"]] == [lead_id]
    assert inbox["escalations"][0]["escalation"]["priority"] == "hot"
    until = (datetime.now(UTC) + timedelta(hours=2)).isoformat()
    assert (
        client.post(
            f"/api/v1/leads/{lead_id}/actions/snooze", json={"until": until}, headers=headers
        ).status_code
        == 200
    )
    _, escalation = await load(sessions, lead_id)
    assert escalation.status == "snoozed"
    far = (datetime.now(UTC) + timedelta(days=30)).isoformat()
    assert (
        client.post(
            f"/api/v1/leads/{lead_id}/actions/snooze", json={"until": far}, headers=headers
        ).status_code
        == 422
    )


async def test_lead_list_filters(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    lead_id = await escalated_lead(sessions)
    viewer, password = await make_user(sessions, "list@railtech.uz", ["viewer"])
    headers = login(client, viewer.email, password)
    page = client.get("/api/v1/leads?stage=handoff&language=ru&q=Азиз", headers=headers).json()
    assert page["total"] == 1
    assert page["items"][0]["id"] == lead_id
    assert client.get("/api/v1/leads?stage=won", headers=headers).json()["total"] == 0
    detail = client.get(f"/api/v1/leads/{lead_id}", headers=headers).json()
    assert detail["tg_username"] == "aziz"
    messages = client.get(f"/api/v1/leads/{lead_id}/messages", headers=headers).json()
    assert [m["role"] for m in messages] == ["lead"]


class FakeChannelBot(FakeSender):
    def __init__(self) -> None:
        super().__init__()
        self.edits: list[dict[str, Any]] = []
        self.posts: list[dict[str, Any]] = []

    async def send_message(self, chat_id: int, text: str, **kwargs: Any) -> Any:
        self.posts.append({"chat_id": chat_id, "text": text, **kwargs})
        return await super().send_message(chat_id, text)

    async def edit_message_text(self, text: str, **kwargs: Any) -> Any:
        self.edits.append({"text": text, **kwargs})
        return True


async def test_channel_post_then_edit_after_take(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    lead_id = await escalated_lead(sessions)
    settings = SettingsService(sessions, ttl_s=0)
    await settings.update("notifications", {"channel_id": -100500, "duty_user_ids": []}, None)
    bot = FakeChannelBot()
    service = NotificationService(sessions, settings, bot)  # type: ignore[arg-type]
    _, escalation = await load(sessions, lead_id)
    assert await service.sync(escalation.id)
    post = bot.posts[0]
    assert post["chat_id"] == -100500
    assert f"Лид #{lead_id}" in post["text"]
    assert post["reply_markup"].inline_keyboard[0][0].callback_data == f"take:{lead_id}"

    manager, password = await make_user(sessions, "ch@railtech.uz", ["manager"])
    client.post(
        f"/api/v1/leads/{lead_id}/actions/take", headers=login(client, manager.email, password)
    )
    assert await service.sync(escalation.id)
    edit = bot.edits[-1]
    assert "✅ Взял: ch" in edit["text"]
    assert edit["reply_markup"] is None


async def test_events_are_delivered_after_commit_only(
    sessions: async_sessionmaker[AsyncSession], live_settings: Settings
) -> None:
    broker = EventBroker(live_settings.libpq_dsn)
    await broker.start()
    try:
        async with broker.subscribe() as queue:
            await asyncio.sleep(0.5)  # LISTEN установлен
            async with sessions() as session, session.begin():
                await events.publish(session, "lead.updated", lead_id=1)
                await session.rollback()
            async with sessions() as session, session.begin():
                await events.publish(session, "lead.updated", lead_id=2)
            event = await asyncio.wait_for(queue.get(), 5)
            assert event == {"type": "lead.updated", "lead_id": 2}
            assert queue.empty()
    finally:
        await broker.stop()
