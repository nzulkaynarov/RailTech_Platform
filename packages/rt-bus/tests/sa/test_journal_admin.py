"""«Журнал интеграций» в Admin (W13-A2), SQLAlchemy: сводка подписчиков, фильтры и страницы доставок, inbox с
ошибками, повторы с автором (pg)."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from datetime import timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from rt_bus import BreakerPolicy, Event, HandlerRegistry
from rt_bus.sqlalchemy import AsyncBus

from ..conftest import T0, Clock, example, example_data, signed
from .conftest import Hub

pytestmark = pytest.mark.pg

DEAL_WON = "uz.railtech.erp.deal.won.v1"
QUOTE_SENT = "uz.railtech.erp.quote.sent.v1"


async def publish(bus: AsyncBus, sessions: async_sessionmaker[AsyncSession], event_type: str, n: int = 1) -> None:
    name = {DEAL_WON: "erp/deal.won.v1", QUOTE_SENT: "erp/quote.sent.v1"}[event_type]
    async with sessions() as session, session.begin():
        for _ in range(n):
            await bus.publish(session, event_type, example_data(name))
    await bus.relay()


async def test_overview_shows_queue_dlq_and_breaker_then_retry_all_dead_with_actor(
    make_bus: Callable[..., AsyncBus],
    sessions: async_sessionmaker[AsyncSession],
    hub: Hub,
    clock: Clock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    bus = make_bus(breaker=BreakerPolicy(threshold=1))
    await publish(bus, sessions, QUOTE_SENT, n=2)  # crm ×2, audit ×2; off (drop) — без строк
    hub.responders["crm"] = lambda r: httpx.Response(410)
    hub.responders["audit"] = lambda r: httpx.Response(503, text="maintenance")
    await bus.deliver()

    overview = await bus.overview()
    assert (overview.service, overview.dlq_size, overview.outbox_pending) == ("erp", 2, 0)
    subs = {s.name: s for s in overview.subscribers}
    assert sorted(subs) == ["audit", "crm", "off"]  # erp подписан на deal.won, но себе издатель не доставляет
    crm, audit = subs["crm"], subs["audit"]
    assert (crm.dead, crm.pending, crm.paused_until, crm.consecutive_failures) == (2, 0, None, 0)
    assert (audit.pending, audit.dead) == (2, 0)
    assert audit.paused_until == clock() + timedelta(seconds=300)
    assert audit.consecutive_failures >= 1
    assert audit.last_error == "HTTP 503: maintenance"
    assert audit.oldest_undelivered_age_seconds == 0.0
    assert (subs["off"].enabled, subs["off"].pending) == (False, 0)

    hub.responders.pop("crm")
    with caplog.at_level(logging.INFO, logger="rt_bus"):
        assert await bus.retry_all_dead("crm", actor="crm-user:7") == 2
        assert await bus.retry_all_dead("crm", actor="crm-user:7") == 0  # повтор идемпотентен: dead больше нет
    [first, second] = [r for r in caplog.records if r.message == "rt_bus_dead_retry_manual"]
    assert (first.actor, first.subscriber, first.count) == ("crm-user:7", "crm", 2)  # type: ignore[attr-defined]
    assert second.count == 0  # type: ignore[attr-defined]
    crm_after = next(s for s in (await bus.subscribers()) if s.name == "crm")
    assert (crm_after.dead, crm_after.pending) == (0, 2)


async def test_retry_delivery_logs_actor_and_ignores_delivered(
    make_bus: Callable[..., AsyncBus],
    sessions: async_sessionmaker[AsyncSession],
    hub: Hub,
    caplog: pytest.LogCaptureFixture,
) -> None:
    bus = make_bus()
    await publish(bus, sessions, DEAL_WON)
    hub.responders["crm"] = lambda r: httpx.Response(404)
    await bus.deliver()
    [dead] = await bus.list_deliveries(status="dead")
    hub.responders.pop("crm")
    with caplog.at_level(logging.INFO, logger="rt_bus"):
        assert await bus.retry_delivery(dead.id, actor="crm-user:3")
    [record] = [r for r in caplog.records if r.message == "rt_bus_delivery_retry_manual"]
    assert (record.delivery_id, record.actor) == (dead.id, "crm-user:3")  # type: ignore[attr-defined]
    assert (await bus.deliver()).delivered == 1
    assert not await bus.retry_delivery(dead.id)  # доставлено — повторять нечего


async def test_deliveries_filter_by_period_and_type_and_page_by_id(
    make_bus: Callable[..., AsyncBus], sessions: async_sessionmaker[AsyncSession], clock: Clock
) -> None:
    bus = make_bus()
    await publish(bus, sessions, DEAL_WON)  # crm
    clock.advance(3600)
    await publish(bus, sessions, QUOTE_SENT)  # crm, audit
    everything = await bus.list_deliveries()
    assert len(everything) == 3
    assert {d.subscriber for d in await bus.list_deliveries(type_contains="quote.sent")} == {"crm", "audit"}
    assert [d.event_type for d in await bus.list_deliveries(created_to=T0 + timedelta(minutes=30))] == [DEAL_WON]
    assert len(await bus.list_deliveries(created_from=T0 + timedelta(minutes=30))) == 2
    assert await bus.list_deliveries(created_from=T0 + timedelta(hours=2)) == []
    first = await bus.list_deliveries(limit=2)
    rest = await bus.list_deliveries(limit=2, before_id=first[-1].id)
    assert [d.id for d in first + rest] == [d.id for d in everything]
    assert len(rest) == 1


@pytest.fixture
def crm(make_bus: Callable[..., AsyncBus]) -> AsyncBus:
    registry = HandlerRegistry()

    @registry.subscribe(QUOTE_SENT)
    async def on_quote(event: Event, session: AsyncSession) -> None:
        if event.data["payload"].get("erp_quote_id") == 666:
            raise ValueError("cannot apply quote 666")

    return make_bus("crm", registry=registry, inbox_retry_delays=(30.0,))


def envelope(bad: bool = False) -> dict[str, Any]:
    env = example("erp/quote.sent.v1")
    env["id"] = str(uuid.uuid4())
    if bad:
        env["data"]["payload"]["erp_quote_id"] = 666
    return env


async def test_inbox_errors_only_shows_failed_and_retrying_and_cursor_keeps_ties(
    crm: AsyncBus, clock: Clock, caplog: pytest.LogCaptureFixture
) -> None:
    ok, retrying, failed = envelope(), envelope(bad=True), envelope(bad=True)
    for env in (ok, retrying, failed):  # одно время приёма у всех трёх: курсор не теряет строки с равным временем
        assert (await crm.receive(*signed(env))).status_code == 200
    assert await crm.process_inbox(ok["id"]) == "processed"
    assert await crm.process_inbox(retrying["id"]) == "received"
    assert await crm.process_inbox(failed["id"]) == "received"
    clock.advance(60)
    assert await crm.process_inbox(failed["id"]) == "failed"

    errors = await crm.list_inbox(errors_only=True)
    assert {str(r.event_id): r.status for r in errors} == {retrying["id"]: "received", failed["id"]: "failed"}
    assert all(r.error == "ValueError: cannot apply quote 666" for r in errors)
    assert [r.status for r in await crm.list_inbox(errors_only=True, type_contains="quote")] != []
    assert await crm.list_inbox(errors_only=True, type_contains="deal.") == []

    pages: list[str] = []
    before, before_id = None, None
    while True:
        page = await crm.list_inbox(limit=1, before=before, before_event_id=before_id)
        if not page:
            break
        pages.append(str(page[0].event_id))
        before, before_id = page[0].received_at, page[0].event_id
    assert sorted(pages) == sorted([ok["id"], retrying["id"], failed["id"]])
    assert len(pages) == 3

    with caplog.at_level(logging.INFO, logger="rt_bus"):
        assert await crm.retry_inbox(failed["id"], actor="crm-user:1")
        assert not await crm.retry_inbox(ok["id"], actor="crm-user:1")  # processed не повторяется
    [record] = [r for r in caplog.records if r.message == "rt_bus_inbox_retry_manual"]
    assert (record.event_id, record.actor) == (failed["id"], "crm-user:1")  # type: ignore[attr-defined]
