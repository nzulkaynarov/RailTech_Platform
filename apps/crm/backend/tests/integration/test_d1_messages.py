"""D1-1 «Переписка менеджера»: событие `lead.message_added`, записка передачи, повтор ответа,
вложения.

Событие — на настоящей БД: строка outbox пишется той же транзакцией, что и сообщение (откат — нет
ни сообщения, ни события; сбой публикации — сообщение откатывается), текста в событии нет, доставка
— только BFF Платформы. Новая передача даёт `lead.updated` с `changed_fields = ["handoff"]`. API:
`GET /inbox` с запиской (CRM-06) читает и наблюдатель (директор Платформы); «Повторить» с тем же
ключом не шлёт второе сообщение; вложение отдаётся по номеру без ключа хранилища.
"""

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bus import runtime, snapshots
from app.bus.runtime import build_bus
from app.config import Settings
from app.domain.triggers import TriggerSignals, evaluate
from app.main import create_app
from app.models.leads import Conversation, Lead, Message
from app.models.qualification import Escalation
from app.services import escalation, message_log
from app.services.conversation_records import RecordsMixin
from app.services.conversation_types import Incoming
from app.services.lead_messenger import LeadMessenger
from app.services.settings import SettingsService
from tests.integration.crm_helpers import FakeSender, escalated_lead, login, make_user

pytestmark = pytest.mark.integration

MESSAGE_ADDED = "uz.railtech.crm.lead.message_added.v1"


@pytest.fixture
def bus(sessions: async_sessionmaker[AsyncSession]) -> Iterator[Any]:
    stand = build_bus(sessions, None)
    runtime.set_bus(stand)
    yield stand
    runtime.set_bus(None)


async def outbox(sessions: async_sessionmaker[AsyncSession]) -> list[dict[str, Any]]:
    async with sessions() as session:
        rows = await session.execute(
            text("SELECT type, subject, envelope FROM rt_bus_outbox ORDER BY created_at, id")
        )
        return [dict(r) for r in rows.mappings().all()]


async def clear_outbox(sessions: async_sessionmaker[AsyncSession]) -> None:
    async with sessions() as session, session.begin():
        await session.execute(text("DELETE FROM rt_bus_outbox"))


async def message_count(sessions: async_sessionmaker[AsyncSession]) -> int:
    async with sessions() as session:
        return int(await session.scalar(select(func.count()).select_from(Message)) or 0)


class Records(RecordsMixin):
    """Запись входящего без хода агента (как бот при лимите частоты) — путь сообщения лида."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions
        self._settings = SettingsService(sessions)


# ── Событие ─────────────────────────────────────────────────────────────────────────────────────


async def test_a_lead_message_is_published_in_its_transaction_without_text(
    sessions: async_sessionmaker[AsyncSession], bus: Any
) -> None:
    lead_id = await escalated_lead(sessions, tg_user_id=6101)
    await clear_outbox(sessions)

    recorded = await Records(sessions).record_lead_message(
        Incoming(tg_user_id=6101, chat_id=6101, text="Есть рельсы Р65 на складе?", message_id=77)
    )

    assert recorded == lead_id
    (row,) = await outbox(sessions)
    assert row["type"] == MESSAGE_ADDED
    assert row["subject"] == f"lead/{lead_id}"
    data = row["envelope"]["data"]
    async with sessions() as session:
        message_id = await session.scalar(select(func.max(Message.id)))
        created_at = await session.scalar(
            select(Message.created_at).where(Message.id == message_id)
        )
    assert created_at is not None
    assert data == {
        "crm_lead_id": lead_id,
        "crm_client_id": None,
        "message_id": message_id,
        "direction": "in",
        "author": "lead",
        "channel": "telegram",
        "has_attachments": False,
        "handoff": True,
        "crm_assigned_user_id": None,
        "sent_at": snapshots.utc(created_at),  # время строки сообщения, а не часы приложения
        "actor": {"type": "bot"},
    }
    assert "Р65" not in str(row["envelope"])  # текст сообщения в шину не уходит

    # Та же транзакция — по факту, а не по часам: строку сообщения и строку outbox записала одна
    # транзакция (одинаковый `xmin`). Время «до Платформы ≤ 2 с» проверяет гейт D1-7 на стенде.
    await Records(sessions).record_lead_message(
        Incoming(tg_user_id=6101, chat_id=6101, text="И шпалы тоже", message_id=78)
    )
    async with sessions() as session:
        pairs = (
            await session.execute(
                text(
                    "SELECT o.envelope -> 'data' ->> 'message_id' AS message_id, "
                    "o.xmin::text AS event_tx, m.xmin::text AS message_tx "
                    "FROM rt_bus_outbox o JOIN messages m "
                    "ON m.id = (o.envelope -> 'data' ->> 'message_id')::bigint "
                    "WHERE o.type = :type ORDER BY o.created_at, o.id"
                ),
                {"type": MESSAGE_ADDED},
            )
        ).all()
    # порядок событий — порядок сообщений, у каждого события — транзакция своего сообщения
    assert [int(p.message_id) for p in pairs] == sorted(int(p.message_id) for p in pairs)
    assert len(pairs) == 2
    assert all(p.event_tx == p.message_tx for p in pairs)
    assert pairs[0].event_tx != pairs[1].event_tx


async def test_manager_reply_is_published_as_outgoing_by_the_staff_member(
    sessions: async_sessionmaker[AsyncSession], live_settings: Settings, bus: Any
) -> None:
    lead_id = await escalated_lead(sessions, tg_user_id=6102)
    manager, password = await make_user(sessions, "d1-out@railtech.uz", ["manager"])
    sender = FakeSender()
    with TestClient(create_app(live_settings)) as client:
        container = client.app.state.container  # type: ignore[attr-defined]
        container.__dict__["lead_messenger"] = LeadMessenger(sessions, sender)
        container.__dict__.pop("lead_service", None)
        me = login(client, manager.email, password)
        assert client.post(f"/api/v1/leads/{lead_id}/actions/take", headers=me).status_code == 200
        await clear_outbox(sessions)
        sent = client.post(
            f"/api/v1/leads/{lead_id}/messages", json={"text": "Добрый день!"}, headers=me
        )
    assert sent.status_code == 200
    (row,) = [r for r in await outbox(sessions) if r["type"] == MESSAGE_ADDED]
    data = row["envelope"]["data"]
    assert (data["direction"], data["author"], data["message_id"]) == (
        "out",
        "manager",
        sent.json()["id"],
    )
    assert data["actor"] == {"type": "staff", "crm_user_id": manager.id}
    assert data["crm_assigned_user_id"] == manager.id


async def test_a_rolled_back_message_leaves_no_event_and_a_publish_failure_drops_the_message(
    sessions: async_sessionmaker[AsyncSession], bus: Any
) -> None:
    lead_id = await escalated_lead(sessions, tg_user_id=6103)
    await clear_outbox(sessions)
    before = await message_count(sessions)

    class BoomError(Exception):
        pass

    async def write_and_fail() -> None:
        async with sessions() as session, session.begin():
            conversation = (
                await session.scalars(select(Conversation).where(Conversation.lead_id == lead_id))
            ).one()
            await message_log.add(session, conversation, role="lead", text="Откатится")
            raise BoomError

    with pytest.raises(BoomError):
        await write_and_fail()
    assert await outbox(sessions) == []
    assert await message_count(sessions) == before

    class BrokenBus:
        async def publish(self, *_: Any, **__: Any) -> None:
            raise RuntimeError("bus is down")

    runtime.set_bus(BrokenBus())  # type: ignore[arg-type]
    try:
        with pytest.raises(RuntimeError, match="bus is down"):
            await Records(sessions).record_lead_message(
                Incoming(tg_user_id=6103, chat_id=6103, text="Не запишется")
            )
    finally:
        runtime.set_bus(bus)
    assert await message_count(sessions) == before


async def test_sandbox_messages_are_not_published(
    sessions: async_sessionmaker[AsyncSession], bus: Any
) -> None:
    async with sessions() as session, session.begin():
        lead = Lead(display_name="Тест админа", stage="new", source="sandbox")
        session.add(lead)
        await session.flush()
        conversation = Conversation(lead_id=lead.id, tg_chat_id=-1)
        session.add(conversation)
        await session.flush()
        await message_log.add(session, conversation, role="lead", text="Привет")
    assert [r for r in await outbox(sessions) if r["type"] == MESSAGE_ADDED] == []


async def test_message_added_is_delivered_only_to_the_platform_bff(
    sessions: async_sessionmaker[AsyncSession], bus: Any
) -> None:
    await escalated_lead(sessions, tg_user_id=6104)
    await clear_outbox(sessions)
    await Records(sessions).record_lead_message(
        Incoming(tg_user_id=6104, chat_id=6104, text="Ещё вопрос")
    )

    assert await bus.relay() == 1
    async with sessions() as session:
        rows = (
            await session.execute(text("SELECT event_type, subscriber FROM rt_bus_delivery"))
        ).all()
    assert [(t, s) for t, s in rows] == [(MESSAGE_ADDED, "platform-bff")]


async def test_a_new_handoff_is_signalled_as_lead_updated(
    sessions: async_sessionmaker[AsyncSession], bus: Any
) -> None:
    cfg = await SettingsService(sessions).get()
    async with sessions() as session, session.begin():
        lead = Lead(display_name="Лид", stage="engaged", owner_mode="bot", consent_given_at=None)
        session.add(lead)
        await session.flush()
        lead_id = lead.id
    await clear_outbox(sessions)

    async with sessions() as session, session.begin():
        fresh = await session.get(Lead, lead_id)
        assert fresh is not None
        hits = evaluate(TriggerSignals(human_requested=True), cfg.escalation.triggers())
        applied = await escalation.apply(session, fresh, hits, cfg, datetime.now(UTC))
        assert applied is not None

    updated = [r for r in await outbox(sessions) if r["type"] == "uz.railtech.crm.lead.updated.v1"]
    assert [r["envelope"]["data"]["changed_fields"] for r in updated] == [["handoff"]]


# ── API: «Ждут ответа», повтор ответа, вложения ─────────────────────────────────────────────────


class StubStorage:
    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}

    async def get(self, bucket: str, key: str) -> bytes:
        return self.files[key]


@pytest.fixture
def api(
    sessions: async_sessionmaker[AsyncSession], live_settings: Settings
) -> Iterator[tuple[TestClient, FakeSender, StubStorage]]:
    sender, storage = FakeSender(), StubStorage()
    with TestClient(create_app(live_settings)) as client:
        container = client.app.state.container  # type: ignore[attr-defined]
        container.__dict__["lead_messenger"] = LeadMessenger(sessions, sender)
        container.__dict__["storage"] = storage
        container.__dict__.pop("lead_service", None)
        yield client, sender, storage


async def test_inbox_carries_the_handoff_note_and_is_readable_by_a_viewer(
    sessions: async_sessionmaker[AsyncSession], api: tuple[TestClient, FakeSender, StubStorage]
) -> None:
    client, _, _ = api
    lead_id = await escalated_lead(sessions, tg_user_id=6201)
    async with sessions() as session, session.begin():
        lead = await session.get(Lead, lead_id)
        assert lead is not None
        lead.need_summary = "Рельсы Р65, 40 т"
        lead.qualification = {"timeline": "<3m", "decision_role": "decision_maker", "x": 1}
        lead.product_interest = ["rails", "unknown-key"]
        row = (await session.scalars(select(Escalation).where(Escalation.lead_id == lead_id))).one()
        row.reason_text = "просит цену"
        row.recommendation = "Позвонить и уточнить объём"
    viewer, password = await make_user(sessions, "d1-viewer@railtech.uz", ["viewer"])

    inbox = client.get("/api/v1/inbox", headers=login(client, viewer.email, password))

    assert inbox.status_code == 200
    (item,) = inbox.json()["escalations"]
    assert item["handoff_note"] == {
        "request": "Рельсы Р65, 40 т",
        "facts": {
            "interest": [],
            "timeline": "<3m",
            "decision_role": "decision_maker",
            "budget_hint": None,
            "company": None,
            "company_size": None,
            "region": None,
        },
        "reason_codes": ["price_or_contract_asked"],
        "reason_text": "просит цену",
        "recommendation": "Позвонить и уточнить объём",
        "last_lead_message": "Сколько стоит?",
    }
    # «Забрать» наблюдателю по-прежнему нельзя
    take = client.post(
        f"/api/v1/leads/{lead_id}/actions/take", headers=login(client, viewer.email, password)
    )
    assert take.status_code == 403


async def test_retry_with_the_same_key_does_not_send_twice(
    sessions: async_sessionmaker[AsyncSession], api: tuple[TestClient, FakeSender, StubStorage]
) -> None:
    client, sender, _ = api
    lead_id = await escalated_lead(sessions, tg_user_id=6202)
    manager, password = await make_user(sessions, "d1-retry@railtech.uz", ["manager"])
    me = login(client, manager.email, password)
    client.post(f"/api/v1/leads/{lead_id}/actions/take", headers=me)
    body = {"text": "Цена — в КП сегодня", "client_message_id": "draft-6202-a1b2c3"}

    first = client.post(f"/api/v1/leads/{lead_id}/messages", json=body, headers=me)
    again = client.post(f"/api/v1/leads/{lead_id}/messages", json=body, headers=me)

    assert first.status_code == again.status_code == 200
    assert first.json()["id"] == again.json()["id"]
    assert [t for _, t in sender.sent].count("Цена — в КП сегодня") == 1
    bad = client.post(
        f"/api/v1/leads/{lead_id}/messages",
        json={"text": "x", "client_message_id": "<script>"},
        headers=me,
    )
    assert bad.status_code == 422


async def test_attachment_is_served_by_number_without_the_storage_key(
    sessions: async_sessionmaker[AsyncSession], api: tuple[TestClient, FakeSender, StubStorage]
) -> None:
    client, _, storage = api
    lead_id = await escalated_lead(sessions, tg_user_id=6203)
    other_id = await escalated_lead(sessions, tg_user_id=6204)
    storage.files["tg/6203/9/Заявка.pdf"] = b"%PDF-1.4 demo"
    async with sessions() as session, session.begin():
        conversation = (
            await session.scalars(select(Conversation).where(Conversation.lead_id == lead_id))
        ).one()
        files = [
            {
                "kind": "file",
                "name": "Заявка.pdf",
                "mime": "application/pdf",
                "size": 13,
                "storage_key": "tg/6203/9/Заявка.pdf",
                "stored": True,
            },
            {"kind": "file", "name": "big.zip", "mime": "application/zip", "stored": False},
        ]
        message = await message_log.add(
            session, conversation, role="lead", text="", attachments=files
        )
        message_id = message.id
    manager, password = await make_user(sessions, "d1-files@railtech.uz", ["manager"])
    me = login(client, manager.email, password)
    base = f"/api/v1/leads/{lead_id}/messages/{message_id}/attachments"

    ok = client.get(f"{base}/0", headers=me)
    assert ok.status_code == 200
    assert ok.content == b"%PDF-1.4 demo"
    assert ok.headers["content-type"] == "application/pdf"
    assert (
        "filename*=UTF-8''%D0%97%D0%B0%D1%8F%D0%B2%D0%BA%D0%B0.pdf"
        in ok.headers["content-disposition"]
    )
    assert ok.headers["cache-control"] == "private, no-store"
    assert client.get(f"{base}/1", headers=me).status_code == 404  # не сохранён
    assert client.get(f"{base}/5", headers=me).status_code == 404  # нет такого номера
    foreign = f"/api/v1/leads/{other_id}/messages/{message_id}/attachments/0"
    assert client.get(foreign, headers=me).status_code == 404  # чужое сообщение
    assert client.get(f"{base}/0").status_code == 401
