"""Издатель: транзакционность outbox; ретранслятор: раскладка по подписчикам (pg)."""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from pathlib import Path

import pytest
import yaml
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from rt_bus import EventValidationError, NotInTransactionError
from rt_bus.sqlalchemy import AsyncBus

from ..conftest import SUBSCRIPTIONS, example_data
from .conftest import rows

pytestmark = pytest.mark.pg

QUOTE_SENT = "uz.railtech.erp.quote.sent.v1"
DEAL_WON = "uz.railtech.erp.deal.won.v1"


async def test_publish_outside_transaction_raises(
    make_bus: Callable[..., AsyncBus], sessions: async_sessionmaker[AsyncSession]
) -> None:
    bus = make_bus()
    async with sessions() as session:
        with pytest.raises(NotInTransactionError):
            await bus.publish(session, QUOTE_SENT, example_data("erp/quote.sent.v1"))
    assert await rows(sessions, "SELECT id FROM rt_bus_outbox") == []


async def test_rollback_leaves_no_outbox_row_commit_leaves_one(
    make_bus: Callable[..., AsyncBus], sessions: async_sessionmaker[AsyncSession]
) -> None:
    bus = make_bus()

    async def change_then_fail() -> None:
        async with sessions() as session, session.begin():
            await bus.publish(session, QUOTE_SENT, example_data("erp/quote.sent.v1"))
            raise RuntimeError("business failed")

    with pytest.raises(RuntimeError, match="business failed"):
        await change_then_fail()
    assert await rows(sessions, "SELECT id FROM rt_bus_outbox") == []

    async with sessions() as session, session.begin():
        event = await bus.publish(session, QUOTE_SENT, example_data("erp/quote.sent.v1"), subject="D-2026-0905")
    [row] = await rows(sessions, "SELECT * FROM rt_bus_outbox")
    assert row["id"] == uuid.UUID(event.id)
    assert (row["type"], row["source"], row["subject"]) == (QUOTE_SENT, "rt://erp", "D-2026-0905")
    envelope = row["envelope"] if isinstance(row["envelope"], dict) else json.loads(row["envelope"])
    assert envelope == event.to_dict()
    assert row["dispatched_at"] is None


async def test_invalid_data_raises_before_write(
    make_bus: Callable[..., AsyncBus], sessions: async_sessionmaker[AsyncSession]
) -> None:
    bus = make_bus()
    async with sessions() as session, session.begin():
        with pytest.raises(EventValidationError):
            await bus.publish(session, QUOTE_SENT, {**example_data("erp/quote.sent.v1"), "unknown": 1})
    assert await rows(sessions, "SELECT id FROM rt_bus_outbox") == []


async def test_relay_fanout_rules(
    make_bus: Callable[..., AsyncBus], sessions: async_sessionmaker[AsyncSession]
) -> None:
    bus = make_bus()
    async with sessions() as session, session.begin():
        quote = await bus.publish(session, QUOTE_SENT, example_data("erp/quote.sent.v1"))
        won = await bus.publish(session, DEAL_WON, example_data("erp/deal.won.v1"))
        # строка с чужим source (не своё событие) — никому
        await session.execute(
            text(
                "INSERT INTO rt_bus_outbox (id, type, source, correlation_id, envelope, created_at) "
                "VALUES (:id, 'uz.railtech.crm.client.updated.v1', 'rt://crm', 'c', CAST('{}' AS jsonb), now())"
            ),
            {"id": uuid.uuid4()},
        )
    assert await bus.relay() == 3
    assert await bus.relay() == 0
    deliveries = await rows(
        sessions, "SELECT event_id, subscriber, status, attempts FROM rt_bus_delivery ORDER BY event_id, subscriber"
    )
    by_event: dict[str, list[str]] = {}
    for d in deliveries:
        assert (d["status"], d["attempts"]) == ("pending", 0)
        by_event.setdefault(str(d["event_id"]), []).append(d["subscriber"])
    # маски: quote.* → crm и audit; deal.won → только crm (erp — сам издатель, off — выключен)
    assert by_event == {quote.id: ["audit", "crm"], won.id: ["crm"]}
    pending = await rows(sessions, "SELECT count(*) AS n FROM rt_bus_outbox WHERE dispatched_at IS NULL")
    assert pending == [{"n": 0}]


async def test_new_subscriber_by_file_line(
    make_bus: Callable[..., AsyncBus], sessions: async_sessionmaker[AsyncSession], subscriptions_file: Path
) -> None:
    bus = make_bus()
    async with sessions() as session, session.begin():
        await bus.publish(session, DEAL_WON, example_data("erp/deal.won.v1"))
    await bus.relay()
    raw = yaml.safe_load(yaml.safe_dump(SUBSCRIPTIONS))
    raw["subscribers"].append(
        {"name": "late", "endpoint": "http://late.test/bus/v1/events", "types": ["uz.railtech.erp.deal.*.v1"]}
    )
    subscriptions_file.write_text(yaml.safe_dump(raw), encoding="utf-8")
    import os

    st = subscriptions_file.stat()
    os.utime(subscriptions_file, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))
    async with sessions() as session, session.begin():
        await bus.publish(session, DEAL_WON, example_data("erp/deal.won.v1"))
    await bus.relay()
    subs = await rows(sessions, "SELECT subscriber FROM rt_bus_delivery ORDER BY id")
    assert [s["subscriber"] for s in subs] == ["crm", "crm", "late"]
    stats = await bus.deliver()
    assert stats.delivered == 3
