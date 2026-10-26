"""Волна 11c (F1), адаптер Django: взаимная блокировка pump (W11B-G-1), `enabled: false` не теряет события
(W11B-G-2), догон после восстановления подписчика (C1-G-6), метрики выключенного подписчика."""

from __future__ import annotations

import contextlib
import os
import threading
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml
from django.db import connection, connections, transaction

from rt_bus.django.bus import DjangoBus

from ..conftest import Clock, example_data
from .conftest import SyncHub, rows

pytestmark = pytest.mark.pg

QUOTE_SENT = "uz.railtech.erp.quote.sent.v1"


def publish(bus: DjangoBus, n: int = 1) -> list[str]:
    with transaction.atomic():
        ids = [bus.publish(QUOTE_SENT, example_data("erp/quote.sent.v1")).id for _ in range(n)]
    bus.relay()
    return ids


def edit_subscriber(path: Path, name: str, **fields: Any) -> None:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    for item in raw["subscribers"]:
        if item["name"] == name:
            item.update(fields)
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    st = path.stat()
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))


def test_parallel_pumps_with_new_subscribers_do_not_deadlock(
    make_bus: Callable[..., DjangoBus], hub: SyncHub, clock: Clock
) -> None:
    """Два pump (потоки, свои соединения) берут crm и audit в разном порядке; строки состояния новые."""
    first, second = make_bus(delivery_batch=2), make_bus(delivery_batch=2)
    for round_no in range(30):
        with connection.cursor() as cursor:
            cursor.execute("TRUNCATE rt_bus_outbox, rt_bus_delivery, rt_bus_subscriber_state RESTART IDENTITY CASCADE")
        publish(first, n=2)
        order = [(0, "crm"), (0, "audit"), (1, "audit"), (1, "crm")]
        with connection.cursor() as cursor:
            for position, (event_index, subscriber) in enumerate(order):
                cursor.execute(
                    "UPDATE rt_bus_delivery "
                    "SET next_attempt_at = %(base)s::timestamptz - make_interval(secs => %(age)s) "
                    "WHERE subscriber = %(s)s AND event_id = (SELECT id FROM rt_bus_outbox ORDER BY created_at, id "
                    "OFFSET %(i)s LIMIT 1)",
                    {"base": clock(), "age": 100 - position, "s": subscriber, "i": event_index},
                )
        gate = threading.Barrier(4, timeout=3)

        def meet(request: httpx.Request, gate: threading.Barrier = gate) -> httpx.Response:
            with contextlib.suppress(threading.BrokenBarrierError):
                gate.wait()  # все четыре ответа уходят одновременно: итоги пишутся внахлёст
            return httpx.Response(200)

        hub.responders["crm"] = hub.responders["audit"] = meet
        errors: list[BaseException] = []
        delivered: list[int] = []

        def work(bus: DjangoBus, errors: list[BaseException] = errors, delivered: list[int] = delivered) -> None:
            try:
                delivered.append(bus.pump().deliver.delivered)
            except BaseException as exc:  # noqa: BLE001 — передать в основной поток
                errors.append(exc)
            finally:
                connections.close_all()

        threads = [threading.Thread(target=work, args=(b,)) for b in (first, second)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        assert errors == [], round_no
        assert sum(delivered) == 4, round_no
        statuses = rows("SELECT subscriber, status FROM rt_bus_delivery")
        assert (
            sorted((r["subscriber"], r["status"]) for r in statuses)
            == [("audit", "delivered")] * 2 + [("crm", "delivered")] * 2
        ), round_no


def test_deadlock_in_record_is_retried_and_does_not_hold_other_subscribers(
    make_bus: Callable[..., DjangoBus], hub: SyncHub, monkeypatch: pytest.MonkeyPatch
) -> None:
    class DeadlockError(Exception):
        pgcode = "40P01"

    bus = make_bus(delivery_batch=10)
    publish(bus, n=2)
    real = DjangoBus._exec
    failed: list[str] = []

    def flaky(self: DjangoBus, statement: str, params: Any = None) -> Any:
        from rt_bus import sql

        if statement == sql.BREAKER_SUCCESS and params["subscriber"] == "audit" and not failed:
            failed.append("audit")
            raise DeadlockError("deadlock detected")
        return real(self, statement, params)

    monkeypatch.setattr(DjangoBus, "_exec", flaky)
    stats = bus.deliver()
    assert failed == ["audit"]
    assert stats.delivered == 4
    assert {r["status"] for r in rows("SELECT status FROM rt_bus_delivery")} == {"delivered"}


def test_other_error_in_record_leaves_other_subscribers_recorded(
    make_bus: Callable[..., DjangoBus], hub: SyncHub, monkeypatch: pytest.MonkeyPatch
) -> None:
    bus = make_bus(delivery_batch=10)
    publish(bus, n=2)
    real = DjangoBus._exec

    def broken(self: DjangoBus, statement: str, params: Any = None) -> Any:
        from rt_bus import sql

        if statement == sql.BREAKER_SUCCESS and params["subscriber"] == "audit":
            raise RuntimeError("boom")
        return real(self, statement, params)

    monkeypatch.setattr(DjangoBus, "_exec", broken)
    with pytest.raises(RuntimeError, match="boom"):
        bus.deliver()
    state = {(r["subscriber"], r["status"]) for r in rows("SELECT subscriber, status FROM rt_bus_delivery")}
    assert state == {("crm", "delivered"), ("audit", "in_flight")}


def test_disabled_subscriber_accumulates_and_delivers_in_order_after_enable(
    make_bus: Callable[..., DjangoBus], hub: SyncHub, subscriptions_file: Path, clock: Clock
) -> None:
    bus = make_bus()
    edit_subscriber(subscriptions_file, "crm", enabled=False)  # drop по умолчанию false
    ids: list[str] = []
    for _ in range(3):
        ids += publish(bus)
        clock.advance(1)
    held = rows("SELECT event_id, status, attempts FROM rt_bus_delivery WHERE subscriber = 'crm'")
    assert sorted(str(r["event_id"]) for r in held) == sorted(ids)
    assert {(r["status"], r["attempts"]) for r in held} == {("pending", 0)}
    assert bus.pump().deliver.delivered == 3  # audit; crm не отправляется
    assert hub.to("crm") == []

    edit_subscriber(subscriptions_file, "crm", enabled=True)
    assert bus.pump().deliver.delivered == 3
    assert [r.headers["x-rt-event-id"] for r in hub.to("crm")] == ids
    assert {r["status"] for r in rows("SELECT status FROM rt_bus_delivery")} == {"delivered"}


def test_disabled_subscriber_with_drop_gets_no_rows(
    make_bus: Callable[..., DjangoBus], hub: SyncHub, subscriptions_file: Path
) -> None:
    bus = make_bus()
    edit_subscriber(subscriptions_file, "crm", enabled=False, drop=True)
    publish(bus, n=2)
    assert rows("SELECT id FROM rt_bus_delivery WHERE subscriber = 'crm'") == []
    edit_subscriber(subscriptions_file, "crm", enabled=True)
    publish(bus)
    bus.pump()
    assert len(hub.to("crm")) == 1


def test_disabled_subscriber_does_not_raise_oldest_age_alert(
    make_bus: Callable[..., DjangoBus], hub: SyncHub, subscriptions_file: Path, clock: Clock
) -> None:
    bus = make_bus()
    edit_subscriber(subscriptions_file, "crm", enabled=False)
    publish(bus, n=2)
    bus.pump()
    clock.advance(2 * 3600)
    metrics = bus.metrics()
    crm = metrics.subscribers["crm"]
    assert (crm.enabled, crm.pending) == (False, 2)
    assert crm.oldest_undelivered_age_seconds is not None
    assert crm.oldest_undelivered_age_seconds >= 2 * 3600
    assert metrics.oldest_undelivered_age_seconds is None
    edit_subscriber(subscriptions_file, "crm", enabled=True)
    metrics = bus.metrics()
    assert metrics.oldest_undelivered_age_seconds is not None
    assert metrics.oldest_undelivered_age_seconds >= 2 * 3600


def test_recovered_subscriber_gets_backlog_immediately(
    make_bus: Callable[..., DjangoBus], hub: SyncHub, clock: Clock
) -> None:
    bus = make_bus(delivery_batch=2)
    publish(bus, n=6)
    hub.responders["crm"] = lambda r: httpx.Response(503)
    bus.pump()
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE rt_bus_delivery SET next_attempt_at = %(far)s WHERE subscriber = 'crm' AND id <> "
            "(SELECT min(id) FROM rt_bus_delivery WHERE subscriber = 'crm')",
            {"far": clock() + timedelta(hours=2)},
        )
    clock.advance(301)
    hub.responders.pop("crm")
    before = len(hub.to("crm"))
    stats = bus.pump()
    assert stats.deliver.recovered == 1
    assert len(hub.to("crm")) - before == 6
    assert {r["status"] for r in rows("SELECT status FROM rt_bus_delivery")} == {"delivered"}
    [state] = rows("SELECT * FROM rt_bus_subscriber_state WHERE subscriber = 'crm'")
    assert (state["consecutive_failures"], state["paused_until"]) == (0, None)
