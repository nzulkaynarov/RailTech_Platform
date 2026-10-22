"""Приёмник и inbox: идемпотентность, skipped, очередь, ошибка обработчика → failed, «повторить», inline (pg)."""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from rt_bus import Event, HandlerRegistry
from rt_bus.sqlalchemy import AsyncBus

from ..conftest import Clock, example, signed
from .conftest import rows

pytestmark = pytest.mark.pg


def envelope(name: str = "erp/quote.sent.v1", **changes: Any) -> dict[str, Any]:
    env = example(name)
    env["id"] = str(uuid.uuid4())
    env.update(changes)
    return env


@pytest.fixture
def calls() -> list[tuple[str, str]]:
    return []


@pytest.fixture
def crm(make_bus: Callable[..., AsyncBus], calls: list[tuple[str, str]]) -> AsyncBus:
    registry = HandlerRegistry()

    @registry.subscribe("uz.railtech.erp.quote.sent.v1")
    async def on_quote(event: Event, session: AsyncSession) -> None:
        # обработчик пишет в той же транзакции, что и статус inbox
        await session.execute(text("SELECT 1"))
        calls.append(("quote", event.id))
        if event.data["payload"].get("erp_quote_id") == 666:
            raise ValueError("cannot apply quote 666")

    bus = make_bus("crm", registry=registry)
    queued: list[str] = []

    async def enqueue(event_id: str) -> None:
        queued.append(event_id)

    bus.enqueue = enqueue
    bus.queued = queued  # type: ignore[attr-defined]
    return bus


async def test_receive_is_idempotent_and_enqueues_once(
    crm: AsyncBus, sessions: async_sessionmaker[AsyncSession], calls: list[tuple[str, str]]
) -> None:
    env = envelope()
    headers, body = signed(env)
    first = await crm.receive(headers, body)
    assert (first.status_code, first.body) == (200, {"status": "received", "id": env["id"]})
    second = await crm.receive(headers, body)
    assert (second.status_code, second.body["status"]) == (200, "duplicate")
    assert crm.queued == [env["id"]]  # type: ignore[attr-defined]
    [row] = await rows(sessions, "SELECT * FROM rt_bus_inbox")
    assert (row["status"], row["publisher"], row["type"], row["correlation_id"]) == (
        "received",
        "erp",
        "uz.railtech.erp.quote.sent.v1",
        env["correlationid"],
    )
    assert await crm.process_inbox(env["id"]) == "processed"
    assert await crm.process_inbox(env["id"]) == "processed"  # повтор задачи — без повторной обработки
    assert calls == [("quote", env["id"])]
    assert await crm.process_inbox(uuid.uuid4()) is None


async def test_skipped_types_are_recorded(crm: AsyncBus, sessions: async_sessionmaker[AsyncSession]) -> None:
    won = envelope("erp/deal.won.v1")
    headers, body = signed(won)
    result = await crm.receive(headers, body)
    assert result.body["status"] == "skipped"
    v2 = envelope(type="uz.railtech.erp.quote.sent.v2", dataschema="rt://contracts/events/erp/quote.sent/v2")
    headers, body = signed(v2)
    assert (await crm.receive(headers, body)).body["status"] == "skipped"
    found = await crm.list_inbox(status="skipped")
    assert {str(r.event_id) for r in found} == {won["id"], v2["id"]}
    assert all(r.error and r.error.startswith("no handler") for r in found)
    assert crm.queued == []  # type: ignore[attr-defined]


async def test_rejections_write_nothing(
    crm: AsyncBus, sessions: async_sessionmaker[AsyncSession], clock: Clock
) -> None:
    env = envelope()
    env["data"]["crm_client_id"] = "x"
    headers, body = signed(env)
    assert (await crm.receive(headers, body)).status_code == 422
    headers, body = signed(envelope(), secret="test-secret-erp-audit")
    assert (await crm.receive(headers, body)).status_code == 401
    assert await rows(sessions, "SELECT event_id FROM rt_bus_inbox") == []


async def test_handler_error_marks_failed_and_retry(
    crm: AsyncBus, sessions: async_sessionmaker[AsyncSession], calls: list[tuple[str, str]]
) -> None:
    env = envelope()
    env["data"]["payload"]["erp_quote_id"] = 666
    headers, body = signed(env)
    await crm.receive(headers, body)
    assert await crm.process_inbox(env["id"]) == "failed"
    [row] = await rows(sessions, "SELECT status, attempts, error FROM rt_bus_inbox")
    assert row == {"status": "failed", "attempts": 1, "error": "ValueError: cannot apply quote 666"}
    assert [r.status for r in await crm.list_inbox(status="failed")] == ["failed"]

    async with sessions() as session, session.begin():
        await session.execute(
            text("UPDATE rt_bus_inbox SET envelope = jsonb_set(envelope, '{data,payload,erp_quote_id}', '1203')")
        )
    assert await crm.retry_inbox(env["id"])
    assert crm.queued[-1] == env["id"]  # type: ignore[attr-defined]
    assert await crm.process_inbox(env["id"]) == "processed"
    assert not await crm.retry_inbox(env["id"])  # processed не повторяется
    assert len(calls) == 2


async def test_enqueue_failure_is_swept(
    crm: AsyncBus, sessions: async_sessionmaker[AsyncSession], clock: Clock
) -> None:
    async def broken(event_id: str) -> None:
        raise ConnectionError("queue down")

    crm.enqueue = broken
    env = envelope()
    headers, body = signed(env)
    assert (await crm.receive(headers, body)).status_code == 200  # запись inbox есть
    assert await crm.requeue_stuck_inbox(older_than=60) == 0
    clock.advance(61)
    crm.enqueue = None  # без очереди — обработать на месте
    assert await crm.requeue_stuck_inbox(older_than=60) == 1
    assert [r.status for r in await crm.list_inbox()] == ["processed"]


async def test_inline_handler_sees_secret_inbox_keeps_mask(
    make_bus: Callable[..., AsyncBus], sessions: async_sessionmaker[AsyncSession]
) -> None:
    registry = HandlerRegistry()
    codes: list[str] = []
    fail = {"on": True}

    @registry.subscribe("uz.railtech.erp.quote.acceptance_code_requested.v1", inline=True)
    async def send_code(event: Event, session: AsyncSession) -> None:
        if fail["on"]:
            raise ConnectionError("telegram down")
        codes.append(event.data["payload"]["code"])

    bus = make_bus("crm", registry=registry)
    env = envelope("erp/quote.acceptance_code_requested.v1")
    headers, body = signed(env)
    result = await bus.receive(headers, body)
    assert (result.status_code, result.body) == (503, {"error": "handler_failed"})
    assert await rows(sessions, "SELECT event_id FROM rt_bus_inbox") == []  # издатель повторит
    fail["on"] = False
    result = await bus.receive(headers, body)
    assert (result.status_code, result.body["status"]) == (200, "processed")
    assert codes == ["000000"]
    [row] = await rows(sessions, "SELECT envelope::text AS e, status FROM rt_bus_inbox")
    assert row["status"] == "processed"
    assert json.loads(row["e"])["data"]["payload"]["code"] == "***"
