"""Волна 13 (A0), W11C-G-1, адаптер SQLAlchemy: медленный, но живой подписчик задерживает только себя.

Подписчик `crm` отвечает 200 через 2,5 с, `audit` — сразу. Раньше пачка уходила параллельно, а итоги писались после
ответа самого медленного и следующая пачка стартовала после этого: `audit` получал запись итога через 2,5 с."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from rt_bus import BreakerPolicy, HandlerRegistry
from rt_bus.sqlalchemy import AsyncBus

from ..conftest import Clock, example_data, make_config
from .conftest import Hub, rows

pytestmark = pytest.mark.pg

QUOTE_SENT = "uz.railtech.erp.quote.sent.v1"
SLOW = 2.5


async def publish(bus: AsyncBus, sessions: async_sessionmaker[AsyncSession], n: int = 1) -> list[str]:
    async with sessions() as session, session.begin():
        ids = [(await bus.publish(session, QUOTE_SENT, example_data("erp/quote.sent.v1"))).id for _ in range(n)]
    await bus.relay()
    return ids


def slow_crm(hub: Hub, seconds: float = SLOW) -> None:
    async def respond(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(seconds)
        return httpx.Response(200)

    hub.responders["crm"] = respond


async def delivered_count(sessions: async_sessionmaker[AsyncSession], subscriber: str) -> int:
    found = await rows(
        sessions,
        "SELECT count(*) AS n FROM rt_bus_delivery WHERE subscriber = :s AND status = 'delivered'",
        s=subscriber,
    )
    return int(found[0]["n"])


async def wait_delivered(
    sessions: async_sessionmaker[AsyncSession], subscriber: str, count: int, *, within: float
) -> float:
    """Через сколько секунд у подписчика стало `count` доставленных; не набралось за `within` — падение."""
    started = time.monotonic()
    while time.monotonic() - started < within:
        if await delivered_count(sessions, subscriber) >= count:
            return time.monotonic() - started
        await asyncio.sleep(0.02)
    pytest.fail(f"{subscriber}: {await delivered_count(sessions, subscriber)} of {count} delivered in {within} s")


async def test_slow_subscriber_does_not_delay_fast_one_in_the_same_batch(
    make_bus: Callable[..., AsyncBus], sessions: async_sessionmaker[AsyncSession], hub: Hub
) -> None:
    """Одна пачка, оба подписчика: итог `audit` записан сразу, не после 2,5 с ответа `crm`."""
    bus = make_bus()
    await publish(bus, sessions, n=3)
    slow_crm(hub)
    task = asyncio.create_task(bus.deliver())
    elapsed = await wait_delivered(sessions, "audit", 3, within=1.0)
    assert elapsed < 1.0
    assert not task.done()  # crm ещё отвечает
    assert await delivered_count(sessions, "crm") == 0
    stats = await task
    assert stats.delivered == 6
    assert await delivered_count(sessions, "crm") == 3


async def test_pump_keeps_delivering_new_events_to_fast_subscriber_while_slow_one_answers(
    make_bus: Callable[..., AsyncBus], sessions: async_sessionmaker[AsyncSession], hub: Hub
) -> None:
    """Событие, опубликованное, пока `crm` отвечает на предыдущее, уходит в `audit` сразу — тем же `pump`."""
    bus = make_bus()
    slow_crm(hub)
    await publish(bus, sessions)
    pump = asyncio.create_task(bus.pump())
    await wait_delivered(sessions, "audit", 1, within=1.0)
    await asyncio.sleep(0.4)
    await publish(bus, sessions)  # crm ещё держит первый запрос
    elapsed = await wait_delivered(sessions, "audit", 2, within=1.5)
    assert elapsed < 1.0
    assert not pump.done()
    stats = await asyncio.wait_for(pump, timeout=10)
    assert stats.deliver.delivered == 4  # pump дождался и своих медленных ответов
    assert await delivered_count(sessions, "crm") == 2


async def test_burst_with_slow_subscriber_keeps_fast_one_quick_and_caps_slow_in_flight(
    make_bus: Callable[..., AsyncBus], sessions: async_sessionmaker[AsyncSession], hub: Hub
) -> None:
    """Всплеск: подписчик с `subscriber_concurrency` запросов в пути пропускает набор пачки, остальные идут."""
    bus = make_bus(delivery_batch=2, subscriber_concurrency=2)
    await publish(bus, sessions, n=6)
    active = peak = 0

    async def respond(request: httpx.Request) -> httpx.Response:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        try:
            await asyncio.sleep(1.0)
        finally:
            active -= 1
        return httpx.Response(200)

    hub.responders["crm"] = respond
    pump = asyncio.create_task(bus.pump())
    elapsed = await wait_delivered(sessions, "audit", 6, within=2.5)
    assert elapsed < 1.5  # шесть доставок audit не ждут crm (шесть ответов по 1 с в два потока — ≈ 3 с)
    stats = await asyncio.wait_for(pump, timeout=20)
    assert stats.deliver.delivered == 12
    assert 1 < peak <= 3  # мягкий предел: пачка из 2 может добавить к двум в пути ещё одну


async def test_slow_subscriber_failure_is_recorded_without_waiting_for_others(
    make_bus: Callable[..., AsyncBus], sessions: async_sessionmaker[AsyncSession], hub: Hub, clock: Clock
) -> None:
    """Повтор и счётчик предохранителя пишутся по подписчику: `crm` отвечает 503 с паузой, `audit` не ждёт."""
    bus = make_bus(breaker=BreakerPolicy(threshold=5))
    await publish(bus, sessions, n=2)

    async def late_503(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.8)
        return httpx.Response(503)

    hub.responders["crm"] = late_503
    task = asyncio.create_task(bus.deliver())
    await wait_delivered(sessions, "audit", 2, within=0.6)
    stats = await task
    assert (stats.delivered, stats.retried) == (2, 2)
    [state] = await rows(sessions, "SELECT consecutive_failures FROM rt_bus_subscriber_state WHERE subscriber = 'crm'")
    assert state["consecutive_failures"] == 2
    pending = await rows(sessions, "SELECT next_attempt_at FROM rt_bus_delivery WHERE subscriber = 'crm'")
    assert all(r["next_attempt_at"] > clock() + timedelta(seconds=20) for r in pending)


async def test_pump_cancellation_interrupts_requests_and_keeps_recorded_results(
    make_bus: Callable[..., AsyncBus], sessions: async_sessionmaker[AsyncSession], hub: Hub
) -> None:
    """Остановка воркера: `pump` отменяется сразу, не дожидаясь медленного ответа; записанное остаётся, остальное —
    `in_flight` под арендой (после её истечения доставки уйдут следующему проходу)."""
    bus = make_bus()
    await publish(bus, sessions, n=2)
    slow_crm(hub)
    pump = asyncio.create_task(bus.pump())
    await wait_delivered(sessions, "audit", 2, within=1.0)
    started = time.monotonic()
    pump.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pump
    assert time.monotonic() - started < 1.0
    states = {
        (r["subscriber"], r["status"]) for r in await rows(sessions, "SELECT subscriber, status FROM rt_bus_delivery")
    }
    assert states == {("audit", "delivered"), ("crm", "in_flight")}


async def test_before_deliver_runs_before_every_claim(
    make_bus: Callable[..., AsyncBus], sessions: async_sessionmaker[AsyncSession], hub: Hub
) -> None:
    """Хук сервиса (CRM обновляет секреты вебхуков) вызывается и в `deliver()`, и в шагах `pump()`."""
    calls = 0

    class Counting(AsyncBus):
        async def before_deliver(self) -> None:
            nonlocal calls
            calls += 1

    plain = make_bus()
    bus = Counting(plain.config, sessions, registry=plain.registry, http=hub.client())
    await publish(bus, sessions, n=2)
    await bus.deliver()
    assert calls == 1
    await publish(bus, sessions, n=1)
    await bus.pump()
    assert calls >= 3  # пачка и завершающий пустой шаг


def test_own_http_client_has_no_connection_cap(
    sessions: async_sessionmaker[AsyncSession], clock: Clock, subscriptions_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Общий потолок пула httpx — узкое место: 100+ запросов медленного подписчика в пути заставляли запрос быстрого
    ждать свободного соединения, то есть чужого ответа (замер W13-A0: 3,6 с до platform-bff). Границу ставит предел на
    подписчика (семафор), а у самого клиента шины потолка нет."""
    captured: dict[str, Any] = {}

    class FakeClient:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    bus = AsyncBus(make_config("erp", clock, subscriptions_file), sessions, registry=HandlerRegistry())
    bus._client()
    assert captured["limits"].max_connections is None


async def test_subscriber_connections_are_capped_across_concurrent_passes(
    make_bus: Callable[..., AsyncBus], sessions: async_sessionmaker[AsyncSession], hub: Hub
) -> None:
    """Предел на подписчика действует на весь процесс. Каждый проход сам насыщается на `subscriber_concurrency` (2)
    запросах и добавляет пачку (2), а проходов три: без общего семафора у медленного подписчика было бы до 3 × 3 = 9
    запросов в пути (мутация `gate=None` — тест красный), с ним — не больше `subscriber_connections` (4)."""
    bus = make_bus(delivery_batch=2, subscriber_concurrency=2)
    assert bus.config.subscriber_connections == 4
    await publish(bus, sessions, n=24)
    active = peak = 0

    async def respond(request: httpx.Request) -> httpx.Response:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        try:
            await asyncio.sleep(0.4)
        finally:
            active -= 1
        return httpx.Response(200)

    hub.responders["crm"] = respond
    pumps = asyncio.gather(bus.pump(), bus.pump(), bus.pump())
    elapsed = await wait_delivered(sessions, "audit", 24, within=3.0)
    assert elapsed < 2.0  # быстрый подписчик не ждёт очереди к медленному
    stats = await asyncio.wait_for(pumps, timeout=60)
    assert sum(s.deliver.delivered for s in stats) == 48
    assert 3 <= peak <= 4


async def test_send_async_gate_limits_concurrent_requests() -> None:
    """Прямой тест `send_async`: семафор на 2 при 10 одновременных попытках — не больше 2 запросов в пути."""
    from datetime import UTC, datetime

    from rt_bus.delivery import Attempt, send_async

    active = peak = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        try:
            await asyncio.sleep(0.05)
        finally:
            active -= 1
        return httpx.Response(200)

    attempt = Attempt(url="http://crm.test/bus/v1/events", headers={}, body=b"{}")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        gate = asyncio.Semaphore(2)
        results = await asyncio.gather(
            *(send_async(client, attempt, 5.0, datetime.now(UTC), deadline=5.0, gate=gate) for _ in range(10))
        )
    assert all(r.status_code == 200 for r in results)
    assert peak == 2


async def test_two_concurrent_pumps_deliver_each_event_once_without_blocking(
    make_bus: Callable[..., AsyncBus], sessions: async_sessionmaker[AsyncSession], hub: Hub
) -> None:
    """Два процесса (две шины на одной базе) с новым циклом `pump`: каждая доставка уходит один раз, взаимных
    блокировок и потерянной аренды нет."""
    first, second = make_bus(delivery_batch=3), make_bus(delivery_batch=3)
    ids = await publish(first, sessions, n=24)

    async def jitter(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.02 + 0.03 * (hash(request.headers["x-rt-event-id"]) % 5) / 4)
        return httpx.Response(200)

    hub.responders["crm"] = hub.responders["audit"] = jitter
    stats = await asyncio.wait_for(asyncio.gather(first.pump(), second.pump()), timeout=30)
    assert sum(s.deliver.delivered for s in stats) == 48
    assert sum(s.deliver.lost_lease for s in stats) == 0
    for subscriber in ("crm", "audit"):
        sent = sorted(r.headers["x-rt-event-id"] for r in hub.to(subscriber))
        assert sent == sorted(ids), subscriber  # ни пропусков, ни повторов
    states = await rows(sessions, "SELECT status, attempts FROM rt_bus_delivery")
    assert {(r["status"], r["attempts"]) for r in states} == {("delivered", 1)}
