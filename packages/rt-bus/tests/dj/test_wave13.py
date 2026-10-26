"""Волна 13 (A0), W11C-G-1, адаптер Django: медленный, но живой подписчик задерживает только себя.

Подписчик `crm` отвечает 200 через 2,5 с, `audit` — сразу. Раньше пул потоков ждал все ответы пачки, итоги писались
после самого медленного, а следующая пачка стартовала после этого."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from datetime import timedelta
from typing import Any

import httpx
import pytest
from django.db import connections, transaction

from rt_bus import BreakerPolicy
from rt_bus.django.bus import DjangoBus

from ..conftest import Clock, example_data
from .conftest import SyncHub, rows

pytestmark = pytest.mark.pg

QUOTE_SENT = "uz.railtech.erp.quote.sent.v1"
SLOW = 2.5


def publish(bus: DjangoBus, n: int = 1) -> list[str]:
    with transaction.atomic():
        ids = [bus.publish(QUOTE_SENT, example_data("erp/quote.sent.v1")).id for _ in range(n)]
    bus.relay()
    return ids


def slow_crm(hub: SyncHub, seconds: float = SLOW, status: int = 200) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        time.sleep(seconds)
        return httpx.Response(status)

    hub.responders["crm"] = respond


def delivered_count(subscriber: str) -> int:
    found = rows(
        "SELECT count(*) AS n FROM rt_bus_delivery WHERE subscriber = %(s)s AND status = 'delivered'", {"s": subscriber}
    )
    return int(found[0]["n"])


def wait_delivered(subscriber: str, count: int, *, within: float) -> float:
    started = time.monotonic()
    while time.monotonic() - started < within:
        if delivered_count(subscriber) >= count:
            return time.monotonic() - started
        time.sleep(0.02)
    pytest.fail(f"{subscriber}: {delivered_count(subscriber)} of {count} delivered in {within} s")


class Worker:
    """`pump`/`deliver` в отдельном потоке (своё соединение), чтобы тест мог смотреть в базу, пока шина ждёт ответов."""

    def __init__(self, call: Callable[[], Any]) -> None:
        self.result: Any = None
        self.error: BaseException | None = None
        self._thread = threading.Thread(target=self._run, args=(call,))
        self._thread.start()

    def _run(self, call: Callable[[], Any]) -> None:
        try:
            self.result = call()
        except BaseException as exc:  # noqa: BLE001 — передать в основной поток
            self.error = exc
        finally:
            connections.close_all()

    @property
    def done(self) -> bool:
        return not self._thread.is_alive()

    def join(self, timeout: float = 20) -> Any:
        self._thread.join(timeout)
        assert self.done, "worker did not finish"
        assert self.error is None, self.error
        return self.result


def test_slow_subscriber_does_not_delay_fast_one_in_the_same_batch(
    make_bus: Callable[..., DjangoBus], hub: SyncHub
) -> None:
    bus = make_bus()
    publish(bus, n=3)
    slow_crm(hub)
    worker = Worker(bus.deliver)
    elapsed = wait_delivered("audit", 3, within=1.0)
    assert elapsed < 1.0
    assert not worker.done  # crm ещё отвечает
    assert delivered_count("crm") == 0
    stats = worker.join()
    assert stats.delivered == 6
    assert delivered_count("crm") == 3


def test_pump_keeps_delivering_new_events_to_fast_subscriber_while_slow_one_answers(
    make_bus: Callable[..., DjangoBus], hub: SyncHub
) -> None:
    bus = make_bus()
    slow_crm(hub)
    publish(bus)
    worker = Worker(bus.pump)
    wait_delivered("audit", 1, within=1.0)
    time.sleep(0.4)
    publish(bus)  # crm ещё держит первый запрос
    elapsed = wait_delivered("audit", 2, within=1.5)
    assert elapsed < 1.0
    assert not worker.done
    stats = worker.join()
    assert stats.deliver.delivered == 4
    assert delivered_count("crm") == 2


def test_burst_with_slow_subscriber_keeps_fast_one_quick_and_caps_slow_in_flight(
    make_bus: Callable[..., DjangoBus], hub: SyncHub
) -> None:
    bus = make_bus(delivery_batch=2, subscriber_concurrency=2)
    publish(bus, n=6)
    lock = threading.Lock()
    state = {"active": 0, "peak": 0}

    def respond(request: httpx.Request) -> httpx.Response:
        with lock:
            state["active"] += 1
            state["peak"] = max(state["peak"], state["active"])
        try:
            time.sleep(1.0)
        finally:
            with lock:
                state["active"] -= 1
        return httpx.Response(200)

    hub.responders["crm"] = respond
    worker = Worker(bus.pump)
    elapsed = wait_delivered("audit", 6, within=2.5)
    assert elapsed < 1.5
    stats = worker.join()
    assert stats.deliver.delivered == 12
    assert 1 < state["peak"] <= 3


def test_slow_subscriber_failure_is_recorded_without_waiting_for_others(
    make_bus: Callable[..., DjangoBus], hub: SyncHub, clock: Clock
) -> None:
    bus = make_bus(breaker=BreakerPolicy(threshold=5))
    publish(bus, n=2)
    slow_crm(hub, 0.8, status=503)
    worker = Worker(bus.deliver)
    wait_delivered("audit", 2, within=0.6)
    stats = worker.join()
    assert (stats.delivered, stats.retried) == (2, 2)
    [state] = rows("SELECT consecutive_failures FROM rt_bus_subscriber_state WHERE subscriber = 'crm'")
    assert state["consecutive_failures"] == 2
    pending = rows("SELECT next_attempt_at FROM rt_bus_delivery WHERE subscriber = 'crm'")
    assert all(r["next_attempt_at"] > clock() + timedelta(seconds=20) for r in pending)


def test_before_deliver_runs_before_every_claim(make_bus: Callable[..., DjangoBus], hub: SyncHub) -> None:
    calls = 0

    class Counting(DjangoBus):
        def before_deliver(self) -> None:
            nonlocal calls
            calls += 1

    plain = make_bus()
    bus = Counting(plain.config, registry=plain.registry, http=hub.client())
    publish(bus, n=2)
    bus.deliver()
    assert calls == 1
    publish(bus, n=1)
    bus.pump()
    assert calls >= 3


def test_own_http_client_has_no_connection_cap(
    clock: Clock, subscriptions_file: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from rt_bus import HandlerRegistry

    from ..conftest import make_config

    captured: dict[str, Any] = {}

    class FakeClient:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(httpx, "Client", FakeClient)
    bus = DjangoBus(make_config("erp", clock, subscriptions_file), registry=HandlerRegistry())
    bus._client()
    assert captured["limits"].max_connections is None


def test_subscriber_connections_are_capped_across_concurrent_passes(
    make_bus: Callable[..., DjangoBus], hub: SyncHub
) -> None:
    """Предел на подписчика действует на весь процесс: три прохода, каждый насыщается на 2 запросах и добавляет
    пачку (2) — без общего семафора у медленного подписчика было бы до 9 запросов (мутация `gate=None` — тест красный),
    с ним — не больше `subscriber_connections` (4)."""
    bus = make_bus(delivery_batch=2, subscriber_concurrency=2)
    assert bus.config.subscriber_connections == 4
    publish(bus, n=24)
    lock = threading.Lock()
    state = {"active": 0, "peak": 0}

    def respond(request: httpx.Request) -> httpx.Response:
        with lock:
            state["active"] += 1
            state["peak"] = max(state["peak"], state["active"])
        try:
            time.sleep(0.4)
        finally:
            with lock:
                state["active"] -= 1
        return httpx.Response(200)

    hub.responders["crm"] = respond
    workers = [Worker(bus.pump), Worker(bus.pump), Worker(bus.pump)]
    elapsed = wait_delivered("audit", 24, within=3.0)
    assert elapsed < 2.0
    delivered = sum(w.join(60).deliver.delivered for w in workers)
    assert delivered == 48
    assert 3 <= state["peak"] <= 4


def test_send_sync_gate_limits_concurrent_requests() -> None:
    """Прямой тест `send_sync`: семафор на 2 при 10 потоках — не больше 2 запросов в пути (без него — 10)."""
    from concurrent.futures import ThreadPoolExecutor
    from datetime import UTC, datetime

    from rt_bus.delivery import Attempt, send_sync

    lock = threading.Lock()
    state = {"active": 0, "peak": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        with lock:
            state["active"] += 1
            state["peak"] = max(state["peak"], state["active"])
        try:
            time.sleep(0.05)
        finally:
            with lock:
                state["active"] -= 1
        return httpx.Response(200)

    attempt = Attempt(url="http://crm.test/bus/v1/events", headers={}, body=b"{}")
    gate = threading.BoundedSemaphore(2)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client, ThreadPoolExecutor(10) as pool:
        futures = [
            pool.submit(send_sync, client, attempt, 5.0, datetime.now(UTC), gate=gate, deadline=5.0) for _ in range(10)
        ]
        results = [f.result() for f in futures]
    assert all(r.status_code == 200 for r in results)
    assert state["peak"] == 2


def test_two_concurrent_pumps_deliver_each_event_once_without_blocking(
    make_bus: Callable[..., DjangoBus], hub: SyncHub
) -> None:
    first, second = make_bus(delivery_batch=3), make_bus(delivery_batch=3)
    ids = publish(first, n=24)

    def jitter(request: httpx.Request) -> httpx.Response:
        time.sleep(0.02 + 0.03 * (hash(request.headers["x-rt-event-id"]) % 5) / 4)
        return httpx.Response(200)

    hub.responders["crm"] = hub.responders["audit"] = jitter
    workers = [Worker(first.pump), Worker(second.pump)]
    stats = [w.join(30) for w in workers]
    assert sum(s.deliver.delivered for s in stats) == 48
    assert sum(s.deliver.lost_lease for s in stats) == 0
    for subscriber in ("crm", "audit"):
        sent = sorted(r.headers["x-rt-event-id"] for r in hub.to(subscriber))
        assert sent == sorted(ids), subscriber
    states = rows("SELECT status, attempts FROM rt_bus_delivery")
    assert {(r["status"], r["attempts"]) for r in states} == {("delivered", 1)}
