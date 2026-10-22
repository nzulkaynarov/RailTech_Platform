"""Доставка: подпись, повторы и jitter, Retry-After, DLQ, ручной повтор, предохранитель, аренда, SKIP LOCKED (pg)."""

from __future__ import annotations

import asyncio
import os
import time
import uuid
from collections.abc import Callable, Mapping
from datetime import timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from rt_bus import ConfigError, MemoryStash, static_secrets, verify
from rt_bus.sqlalchemy import AsyncBus

from ..conftest import SECRETS, Clock, example_data, make_config
from .conftest import Hub, rows

pytestmark = pytest.mark.pg

QUOTE_SENT = "uz.railtech.erp.quote.sent.v1"
DEAL_WON = "uz.railtech.erp.deal.won.v1"
CODE = "uz.railtech.erp.quote.acceptance_code_requested.v1"


async def publish(
    bus: AsyncBus, sessions: async_sessionmaker[AsyncSession], event_type: str = DEAL_WON, n: int = 1
) -> list[str]:
    names = {
        DEAL_WON: "erp/deal.won.v1",
        QUOTE_SENT: "erp/quote.sent.v1",
        CODE: "erp/quote.acceptance_code_requested.v1",
    }
    ids = []
    async with sessions() as session, session.begin():
        for _ in range(n):
            ids.append((await bus.publish(session, event_type, example_data(names[event_type]))).id)
    await bus.relay()
    return ids


async def delivery(sessions: async_sessionmaker[AsyncSession], subscriber: str = "crm") -> dict:  # type: ignore[type-arg]
    [row] = await rows(sessions, "SELECT * FROM rt_bus_delivery WHERE subscriber = :s", s=subscriber)
    return row


async def test_signed_post_and_no_lock_during_http(
    make_bus: Callable[..., AsyncBus], sessions: async_sessionmaker[AsyncSession], hub: Hub, clock: Clock
) -> None:
    bus = make_bus()
    from rt_bus import correlation

    tp = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
    with correlation("req-1", tp):
        [event_id] = await publish(bus, sessions)
    locks_free: list[bool] = []

    async def crm(request: httpx.Request) -> httpx.Response:
        # HTTP идёт вне транзакции: строку доставки можно заблокировать без ожидания
        async with sessions() as session, session.begin():
            got = (
                await session.execute(
                    text("SELECT id FROM rt_bus_delivery WHERE event_id = :e FOR UPDATE NOWAIT"),
                    {"e": uuid.UUID(event_id)},
                )
            ).all()
            locks_free.append(len(got) == 1)
        return httpx.Response(202)

    hub.responders["crm"] = crm
    stats = await bus.deliver()
    assert (stats.claimed, stats.delivered) == (1, 1)
    assert locks_free == [True]
    [request] = hub.to("crm")
    assert str(request.url) == "http://crm.test/bus/v1/events"
    h = request.headers
    assert h["content-type"] == "application/cloudevents+json"
    assert (h["x-rt-publisher"], h["x-rt-event-id"], h["x-rt-timestamp"]) == ("erp", event_id, "2026-10-23T09:00:00Z")
    assert (h["x-request-id"], h["traceparent"]) == ("req-1", tp)
    # подписано первым (текущим) секретом пары
    assert verify(["test-secret-erp-crm-new"], event_id, h["x-rt-timestamp"], request.content, h["x-rt-signature"])
    row = await delivery(sessions)
    assert (row["status"], row["attempts"], row["last_status_code"]) == ("delivered", 1, 202)
    assert row["delivered_at"] == clock()
    assert await bus.deliver() == type(stats)()


async def test_endpoint_env_override(
    make_bus: Callable[..., AsyncBus],
    sessions: async_sessionmaker[AsyncSession],
    hub: Hub,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RT_BUS_ENDPOINT_CRM", "http://crm-api.internal:8000/bus/v1/events")
    bus = make_bus()
    await publish(bus, sessions)
    await bus.deliver()
    assert [str(r.url) for r in hub.requests] == ["http://crm-api.internal:8000/bus/v1/events"]


async def test_retry_schedule_jitter_and_dead_after_sixth_retry(
    make_bus: Callable[..., AsyncBus], sessions: async_sessionmaker[AsyncSession], hub: Hub, clock: Clock
) -> None:
    bus = make_bus()
    await publish(bus, sessions)
    hub.responders["crm"] = lambda r: httpx.Response(500, text="boom")
    signatures = set()
    for attempt, base in enumerate([30, 120, 600, 3600, 21600, 86400], start=1):
        stats = await bus.deliver()
        assert stats.retried == 1, attempt
        row = await delivery(sessions)
        assert (row["status"], row["attempts"]) == ("pending", attempt)
        assert row["last_error"] == "HTTP 500: boom"
        delay = (row["next_attempt_at"] - clock()).total_seconds()
        assert base * 0.8 <= delay <= base * 1.2
        assert await bus.deliver() == type(stats)()  # раньше срока — не берётся
        clock.current = row["next_attempt_at"]
        signatures.add(hub.requests[-1].headers["x-rt-signature"])
    stats = await bus.deliver()
    assert stats.dead == 1
    row = await delivery(sessions)
    assert (row["status"], row["attempts"], row["next_attempt_at"]) == ("dead", 7, None)
    assert "retries exhausted after 7 attempts" in row["last_error"]
    assert len(hub.to("crm")) == 7
    assert len(signatures) == 6  # метка и подпись — заново на каждую попытку


async def test_retry_after_429(
    make_bus: Callable[..., AsyncBus], sessions: async_sessionmaker[AsyncSession], hub: Hub, clock: Clock
) -> None:
    bus = make_bus()
    await publish(bus, sessions)
    hub.responders["crm"] = lambda r: httpx.Response(429, headers={"Retry-After": "45"})
    await bus.deliver()
    row = await delivery(sessions)
    assert 45 <= (row["next_attempt_at"] - clock()).total_seconds() <= 54  # max(45, шаг 30) + jitter вверх
    clock.current = row["next_attempt_at"]
    hub.responders["crm"] = lambda r: httpx.Response(503, headers={"Retry-After": "1"})
    await bus.deliver()
    row = await delivery(sessions)
    assert 96 <= (row["next_attempt_at"] - clock()).total_seconds() <= 144  # шаг 2 мин, не 1 с


async def test_network_error_is_retried(
    make_bus: Callable[..., AsyncBus], sessions: async_sessionmaker[AsyncSession], hub: Hub
) -> None:
    bus = make_bus()
    await publish(bus, sessions)

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    hub.responders["crm"] = down
    stats = await bus.deliver()
    assert stats.retried == 1
    assert (await delivery(sessions))["last_error"].startswith("ConnectError")


async def test_permanent_errors_dead_then_manual_retry(
    make_bus: Callable[..., AsyncBus], sessions: async_sessionmaker[AsyncSession], hub: Hub
) -> None:
    bus = make_bus()
    await publish(bus, sessions, QUOTE_SENT, n=2)
    hub.responders["crm"] = lambda r: httpx.Response(422, json={"error": "invalid_data"})
    stats = await bus.deliver()
    assert (stats.dead, stats.delivered) == (2, 2)  # crm — dead сразу; audit — доставлено
    dead = await bus.list_deliveries(status="dead")
    assert {(d.subscriber, d.attempts, d.last_status_code) for d in dead} == {("crm", 1, 422)}
    assert dead[0].subject is None
    assert dead[0].correlation_id
    # предохранитель неповторяемые ответы не считает
    assert await rows(sessions, "SELECT subscriber FROM rt_bus_subscriber_state WHERE consecutive_failures > 0") == []

    hub.responders.pop("crm")
    assert await bus.retry_delivery(dead[0].id)
    assert not await bus.retry_delivery(dead[0].id + 10_000)
    stats = await bus.deliver()
    assert stats.delivered == 1
    assert await bus.retry_all_dead(subscriber="audit") == 0
    assert await bus.retry_all_dead() == 1
    assert (await bus.deliver()).delivered == 1
    assert await bus.list_deliveries(status="dead") == []
    assert len(await bus.list_deliveries(subscriber="crm")) == 2
    assert len(await bus.list_deliveries(limit=1)) == 1


async def test_breaker_pauses_one_subscriber_then_probes(
    make_bus: Callable[..., AsyncBus], sessions: async_sessionmaker[AsyncSession], hub: Hub, clock: Clock
) -> None:
    bus = make_bus(delivery_batch=20)
    await publish(bus, sessions, QUOTE_SENT, n=5)
    hub.responders["crm"] = lambda r: httpx.Response(503)
    stats = await bus.deliver()
    assert (stats.retried, stats.delivered) == (5, 5)  # crm падает, audit идёт
    [state] = await rows(sessions, "SELECT * FROM rt_bus_subscriber_state WHERE subscriber = 'crm'")
    assert state["consecutive_failures"] == 5
    assert state["paused_until"] == clock() + timedelta(seconds=300)

    # пауза: crm не трогаем, другие подписчики получают новые события
    await publish(bus, sessions, QUOTE_SENT, n=2)
    clock.advance(120)
    before = len(hub.to("crm"))
    stats = await bus.deliver()
    assert len(hub.to("crm")) == before
    assert stats.delivered == 2

    # после паузы — ровно одна пробная доставка, хотя готовы все 7
    clock.advance(181)
    hub.responders.pop("crm")
    stats = await bus.deliver()
    assert (stats.claimed, stats.delivered) == (1, 1)
    [state] = await rows(sessions, "SELECT * FROM rt_bus_subscriber_state WHERE subscriber = 'crm'")
    assert (state["consecutive_failures"], state["paused_until"]) == (0, None)
    stats = await bus.deliver()
    assert stats.delivered == 6


async def test_failed_probe_pauses_again(
    make_bus: Callable[..., AsyncBus], sessions: async_sessionmaker[AsyncSession], hub: Hub, clock: Clock
) -> None:
    bus = make_bus()
    await publish(bus, sessions, n=6)
    hub.responders["crm"] = lambda r: httpx.Response(500)
    await bus.deliver()
    clock.advance(301)
    stats = await bus.deliver()
    assert stats.claimed == 1
    [state] = await rows(sessions, "SELECT * FROM rt_bus_subscriber_state WHERE subscriber = 'crm'")
    assert state["consecutive_failures"] == 7
    assert state["paused_until"] == clock() + timedelta(seconds=300)
    assert (await bus.deliver()).claimed == 0


async def test_skip_locked_rows_are_not_waited_for(
    make_bus: Callable[..., AsyncBus], sessions: async_sessionmaker[AsyncSession], hub: Hub
) -> None:
    bus = make_bus()
    await publish(bus, sessions, n=3)
    async with sessions() as holder, holder.begin():
        locked = (await holder.execute(text("SELECT id FROM rt_bus_delivery ORDER BY id LIMIT 2 FOR UPDATE"))).all()
        stats = await asyncio.wait_for(bus.deliver(), timeout=5)
        assert stats.claimed == 1  # две строки заняты другим воркером — пропущены, не ждём
    assert len(locked) == 2
    assert (await bus.deliver()).delivered == 2


async def test_two_workers_deliver_each_event_once(
    make_bus: Callable[..., AsyncBus], sessions: async_sessionmaker[AsyncSession], hub: Hub
) -> None:
    first, second = make_bus(delivery_batch=5), make_bus(delivery_batch=5)
    ids = await publish(first, sessions, n=12)

    async def slow(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.02)
        return httpx.Response(200)

    hub.responders["crm"] = slow
    for _ in range(4):
        await asyncio.gather(first.deliver(), second.deliver())
    sent = [r.headers["x-rt-event-id"] for r in hub.to("crm")]
    assert sorted(sent) == sorted(ids)
    assert await rows(sessions, "SELECT count(*) AS n FROM rt_bus_delivery WHERE status = 'delivered'") == [{"n": 12}]


async def test_lease_expiry_and_lost_lease(
    make_bus: Callable[..., AsyncBus], sessions: async_sessionmaker[AsyncSession], hub: Hub, clock: Clock
) -> None:
    crashed, healthy = make_bus(), make_bus()
    await publish(crashed, sessions)
    [(claimed, _)] = await crashed._claim(clock(), 10)  # воркер взял доставку и «упал»
    assert (await delivery(sessions))["status"] == "in_flight"
    assert (await healthy.deliver()).claimed == 0  # аренда ещё действует
    clock.advance(61)
    stats = await healthy.deliver()
    assert stats.delivered == 1
    row = await delivery(sessions)
    assert (row["status"], row["attempts"]) == ("delivered", 2)
    # упавший воркер «очнулся»: его итог не затирает чужой
    from rt_bus.core import DeliverStats
    from rt_bus.delivery import Outcome, OutcomeKind

    stats = DeliverStats()
    async with sessions() as session, session.begin():
        await crashed._record(session, claimed, Outcome(OutcomeKind.DEAD, error="late"), clock(), stats)
    assert stats.lost_lease == 1
    assert (await delivery(sessions))["status"] == "delivered"


async def test_missing_secret_postpones_without_counting(
    make_bus: Callable[..., AsyncBus], sessions: async_sessionmaker[AsyncSession], hub: Hub, clock: Clock
) -> None:
    secrets = {k: v for k, v in SECRETS.items() if k != ("erp", "crm")}
    bus = make_bus(secrets=static_secrets(secrets))
    await publish(bus, sessions)
    stats = await bus.deliver()
    assert (stats.postponed, len(hub.requests)) == (1, 0)
    row = await delivery(sessions)
    assert (row["status"], row["attempts"]) == ("pending", 0)
    assert row["last_error"] == "no secret RT_BUS_SECRET_ERP_CRM"
    assert row["next_attempt_at"] == clock() + timedelta(seconds=300)


async def test_publisher_secret_fields_stay_out_of_outbox(
    sessions: async_sessionmaker[AsyncSession], hub: Hub, clock: Clock, make_bus: Callable[..., AsyncBus]
) -> None:
    class Stash:
        def __init__(self) -> None:
            self.inner = MemoryStash()

        async def put(self, event_id: str, values: Mapping[str, Any]) -> None:
            self.inner.put(event_id, values)

        async def get(self, event_id: str) -> Mapping[str, Any] | None:
            return self.inner.get(event_id)

    bus = make_bus()
    bus.stash = stash = Stash()
    [first, second] = await publish(bus, sessions, CODE, n=2)
    stored = await rows(sessions, "SELECT envelope::text AS e FROM rt_bus_outbox")
    assert all('"code": "***"' in r["e"] or '"code":"***"' in r["e"] for r in stored)
    assert all('"000000"' not in r["e"] for r in stored)
    stash.inner.values.pop(second)  # секрет истёк
    stats = await bus.deliver()
    assert (stats.delivered, stats.dead) == (2, 2)  # crm и audit: первое доставлено, второе — dead
    [request] = hub.to("crm")
    assert b'"code":"000000"' in request.content
    dead = await bus.list_deliveries(status="dead")
    assert all((d.last_error or "").startswith("SECRET_EXPIRED") for d in dead)
    assert {str(d.event_id) for d in dead} == {second}
    assert first != second


async def test_metrics_and_purge(
    make_bus: Callable[..., AsyncBus],
    sessions: async_sessionmaker[AsyncSession],
    hub: Hub,
    clock: Clock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    bus = make_bus()
    await publish(bus, sessions, QUOTE_SENT, n=2)
    async with sessions() as session, session.begin():
        await bus.publish(session, DEAL_WON, example_data("erp/deal.won.v1"))
    hub.responders["crm"] = lambda r: httpx.Response(404)
    hub.responders["audit"] = lambda r: httpx.Response(500)
    await bus.deliver()
    clock.advance(600)
    with caplog.at_level("INFO", logger="rt_bus.metrics"):
        metrics = await bus.log_metrics()
    assert metrics.outbox_pending == 1
    assert metrics.dlq_size == 2
    assert metrics.subscribers["crm"].dead == 2
    assert metrics.subscribers["audit"].pending == 2
    assert metrics.oldest_undelivered_age_seconds == 600
    assert "rt_bus_metrics service=erp outbox_pending=1" in caplog.text

    hub.responders.clear()
    await bus.relay()
    await bus.retry_all_dead()
    clock.advance(10_000)
    await bus.deliver()
    clock.advance(86400 * 31)
    assert await bus.purge() == {"deliveries": 5, "outbox": 3, "inbox": 0}


async def test_secret_fields_without_stash_fail_closed(
    make_bus: Callable[..., AsyncBus], sessions: async_sessionmaker[AsyncSession]
) -> None:
    bus = make_bus()
    async with sessions() as session, session.begin():
        with pytest.raises(ConfigError, match="secret fields"):
            await bus.publish(session, CODE, example_data("erp/quote.acceptance_code_requested.v1"))
    assert await rows(sessions, "SELECT id FROM rt_bus_outbox") == []


async def test_slow_response_hits_attempt_deadline(
    make_bus: Callable[..., AsyncBus], sessions: async_sessionmaker[AsyncSession], hub: Hub
) -> None:
    bus = make_bus(http_timeout=0.05, attempt_deadline=0.2)
    await publish(bus, sessions)

    async def dripping(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(5)  # таймаут httpx на операцию такой ответ не ловит
        return httpx.Response(200)

    hub.responders["crm"] = dripping
    started = time.monotonic()
    stats = await bus.deliver()
    assert time.monotonic() - started < 2
    assert stats.retried == 1
    row = await delivery(sessions)
    assert (row["status"], row["last_error"]) == ("pending", "DeadlineExceeded: no complete response within 0.2 s")


def test_deadline_must_fit_lease(clock: Clock, subscriptions_file: Path) -> None:
    with pytest.raises(ConfigError):
        make_config("erp", clock, subscriptions_file, attempt_deadline=55)
    with pytest.raises(ConfigError):
        make_config("erp", clock, subscriptions_file, http_timeout=30, attempt_deadline=20)


async def test_disabled_subscriber_deliveries_wait(
    make_bus: Callable[..., AsyncBus], sessions: async_sessionmaker[AsyncSession], hub: Hub, subscriptions_file: Path
) -> None:
    bus = make_bus()
    await publish(bus, sessions, n=2)  # разложено crm до выключения
    set_enabled(subscriptions_file, "crm", enabled=False)
    stats = await bus.deliver()
    assert (stats.claimed, hub.to("crm")) == (0, [])
    assert {r["status"] for r in await rows(sessions, "SELECT status FROM rt_bus_delivery")} == {"pending"}
    set_enabled(subscriptions_file, "crm", enabled=True)
    assert (await bus.deliver()).delivered == 2


async def test_permanent_answer_to_probe_closes_breaker(
    make_bus: Callable[..., AsyncBus], sessions: async_sessionmaker[AsyncSession], hub: Hub, clock: Clock
) -> None:
    bus = make_bus()
    await publish(bus, sessions, n=6)
    hub.responders["crm"] = lambda r: httpx.Response(503)
    await bus.deliver()
    clock.advance(301)
    hub.responders["crm"] = lambda r: httpx.Response(422)  # подписчик жив, но это событие не примет
    stats = await bus.deliver()
    assert (stats.claimed, stats.dead) == (1, 1)
    [state] = await rows(sessions, "SELECT * FROM rt_bus_subscriber_state WHERE subscriber = 'crm'")
    assert (state["consecutive_failures"], state["paused_until"]) == (0, None)
    hub.responders.pop("crm")
    assert (await bus.deliver()).delivered == 5


def set_enabled(path: Path, name: str, *, enabled: bool) -> None:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    for item in raw["subscribers"]:
        if item["name"] == name:
            item["enabled"] = enabled
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    st = path.stat()
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))
