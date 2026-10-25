"""Адаптер Django: те же правила §2 на ORM-соединении Django (psycopg2 — как ERP, и psycopg 3)."""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from django.db import connection, connections, transaction
from django.test import Client

from rt_bus import (
    ConfigError,
    CorrelationFilter,
    Event,
    HandlerRegistry,
    InTransactionError,
    NotInTransactionError,
    get_correlation_id,
    verify,
)
from rt_bus.django.bus import DjangoBus
from tests import django_support

from ..conftest import Clock, example, example_data, signed
from .conftest import DRIVER, SyncHub, rows

pytestmark = pytest.mark.pg

DEAL_WON = "uz.railtech.erp.deal.won.v1"
QUOTE_SENT = "uz.railtech.erp.quote.sent.v1"


def publish(bus: DjangoBus, event_type: str = DEAL_WON, n: int = 1) -> list[str]:
    name = {DEAL_WON: "erp/deal.won.v1", QUOTE_SENT: "erp/quote.sent.v1"}[event_type]
    with transaction.atomic():
        ids = [bus.publish(event_type, example_data(name)).id for _ in range(n)]
    bus.relay()
    return ids


def delivery(subscriber: str = "crm") -> dict[str, Any]:
    [row] = rows("SELECT * FROM rt_bus_delivery WHERE subscriber = %(s)s", {"s": subscriber})
    return row


def test_driver_matches_request() -> None:
    from django.db.backends.postgresql.psycopg_any import is_psycopg3

    assert is_psycopg3 is (DRIVER == "psycopg")
    assert connection.vendor == "postgresql"


def test_publish_requires_atomic_and_rolls_back(make_bus: Callable[..., DjangoBus]) -> None:
    woke: list[int] = []
    bus = make_bus()
    bus.wakeup = lambda: woke.append(1)
    with pytest.raises(NotInTransactionError):
        bus.publish(DEAL_WON, example_data("erp/deal.won.v1"))

    def change_then_fail() -> None:
        with transaction.atomic():
            bus.publish(DEAL_WON, example_data("erp/deal.won.v1"))
            raise RuntimeError("business failed")

    with pytest.raises(RuntimeError):
        change_then_fail()
    assert rows("SELECT id FROM rt_bus_outbox") == []
    assert woke == []
    with transaction.atomic():
        event = bus.publish(DEAL_WON, example_data("erp/deal.won.v1"), subject="D-2026-0905")
        assert woke == []  # будим ретранслятор только после коммита
    assert woke == [1]
    [row] = rows("SELECT id, subject, envelope FROM rt_bus_outbox")
    assert (str(row["id"]), row["subject"]) == (event.id, "D-2026-0905")
    envelope = row["envelope"] if isinstance(row["envelope"], dict) else json.loads(row["envelope"])
    assert envelope == event.to_dict()


def test_wakeup_is_one_per_transaction_and_follows_the_outer_commit(make_bus: Callable[..., DjangoBus]) -> None:
    woke: list[int] = []
    bus = make_bus()
    bus.wakeup = lambda: woke.append(1)
    with transaction.atomic():
        bus.publish(DEAL_WON, example_data("erp/deal.won.v1"))
        with transaction.atomic():  # вложенный блок (SAVEPOINT) тоже публикует
            bus.publish(DEAL_WON, example_data("erp/deal.won.v1"))
        bus.publish(DEAL_WON, example_data("erp/deal.won.v1"))
        assert woke == []
    assert woke == [1]  # три publish — одно пробуждение
    assert len(rows("SELECT id FROM rt_bus_outbox")) == 3
    with transaction.atomic():
        bus.publish(DEAL_WON, example_data("erp/deal.won.v1"))
    assert woke == [1, 1]  # новая транзакция — новое пробуждение


def test_wakeup_savepoint_rollback_does_not_wake_or_leave_a_mark(make_bus: Callable[..., DjangoBus]) -> None:
    woke: list[int] = []
    bus = make_bus()
    bus.wakeup = lambda: woke.append(1)
    with transaction.atomic():
        try:
            with transaction.atomic():
                bus.publish(DEAL_WON, example_data("erp/deal.won.v1"))
                raise RuntimeError("savepoint rolled back")
        except RuntimeError:
            pass
        bus.publish(DEAL_WON, example_data("erp/deal.won.v1"))  # отметка отката ушла вместе с точкой сохранения
    assert woke == [1]
    assert len(rows("SELECT id FROM rt_bus_outbox")) == 1
    with transaction.atomic():
        try:
            with transaction.atomic():
                bus.publish(DEAL_WON, example_data("erp/deal.won.v1"))
                raise RuntimeError("savepoint rolled back")
        except RuntimeError:
            pass
    assert woke == [1]  # от публикации в отменённой точке сохранения будить некого


def test_wakeup_failure_does_not_break_publish(
    make_bus: Callable[..., DjangoBus], caplog: pytest.LogCaptureFixture
) -> None:
    def broker_down() -> None:
        raise ConnectionError("broker is down")

    bus = make_bus()
    bus.wakeup = broker_down
    with caplog.at_level(logging.ERROR, logger="rt_bus"), transaction.atomic():
        bus.publish(DEAL_WON, example_data("erp/deal.won.v1"))
    assert "rt_bus_wakeup_failed" in caplog.text
    assert len(rows("SELECT id FROM rt_bus_outbox")) == 1  # событие на месте, дойдёт периодическим проходом
    assert bus.pump().relayed == 1


def test_relay_and_signed_delivery_without_locks(make_bus: Callable[..., DjangoBus], hub: SyncHub) -> None:
    bus = make_bus()
    [quote] = publish(bus, QUOTE_SENT)
    [won] = publish(bus, DEAL_WON)
    subs = rows("SELECT event_id, subscriber FROM rt_bus_delivery ORDER BY subscriber, event_id")
    assert sorted((str(r["event_id"]), r["subscriber"]) for r in subs) == sorted(
        [(quote, "audit"), (quote, "crm"), (won, "crm")]
    )
    free: list[bool] = []

    def crm(request: httpx.Request) -> httpx.Response:
        conn = connections.create_connection("default")  # другой воркер: строка не заблокирована
        try:
            with conn.cursor() as cur:
                cur.execute("BEGIN")
                cur.execute(
                    "SELECT id FROM rt_bus_delivery WHERE event_id = %(e)s AND subscriber = 'crm' FOR UPDATE NOWAIT",
                    {"e": uuid.UUID(request.headers["x-rt-event-id"])},
                )
                free.append(len(cur.fetchall()) == 1)
                cur.execute("ROLLBACK")
        finally:
            conn.close()
        return httpx.Response(200)

    hub.responders["crm"] = crm
    stats = bus.deliver()
    assert (stats.claimed, stats.delivered) == (3, 3)
    assert free == [True, True]
    request = next(r for r in hub.to("crm") if r.headers["x-rt-event-id"] == won)
    h = request.headers
    assert verify(["test-secret-erp-crm-new"], won, h["x-rt-timestamp"], request.content, h["x-rt-signature"])
    assert h["x-rt-publisher"] == "erp"


def test_retries_dead_and_manual_retry(make_bus: Callable[..., DjangoBus], hub: SyncHub, clock: Clock) -> None:
    bus = make_bus()
    publish(bus)
    hub.responders["crm"] = lambda r: httpx.Response(502)
    for attempt, base in enumerate([30, 120, 600, 3600, 21600, 86400], start=1):
        assert bus.deliver().retried == 1
        row = delivery()
        assert row["attempts"] == attempt
        assert base * 0.8 <= (row["next_attempt_at"] - clock()).total_seconds() <= base * 1.2
        clock.current = row["next_attempt_at"]
    assert bus.deliver().dead == 1
    [dead] = bus.list_deliveries(status="dead")
    assert dead.attempts == 7
    hub.responders.pop("crm")
    assert bus.retry_delivery(dead.id)
    assert bus.deliver().delivered == 1
    hub.responders["crm"] = lambda r: httpx.Response(410)
    publish(bus)
    assert bus.deliver().dead == 1
    assert bus.retry_all_dead("crm") == 1
    hub.responders.pop("crm")
    assert bus.deliver().delivered == 1


def test_retry_after(make_bus: Callable[..., DjangoBus], hub: SyncHub, clock: Clock) -> None:
    bus = make_bus()
    publish(bus)
    hub.responders["crm"] = lambda r: httpx.Response(503, headers={"Retry-After": "90"})
    bus.deliver()
    assert 90 <= (delivery()["next_attempt_at"] - clock()).total_seconds() <= 108


def test_breaker(make_bus: Callable[..., DjangoBus], hub: SyncHub, clock: Clock) -> None:
    bus = make_bus(delivery_batch=20)
    publish(bus, QUOTE_SENT, n=5)
    hub.responders["crm"] = lambda r: httpx.Response(500)
    stats = bus.deliver()
    assert (stats.retried, stats.delivered) == (5, 5)
    publish(bus, QUOTE_SENT, n=1)
    clock.advance(100)
    assert bus.deliver().delivered == 1  # audit идёт, crm на паузе
    clock.advance(201)
    hub.responders.pop("crm")
    assert bus.deliver().claimed == 1  # одна пробная
    assert bus.deliver().delivered == 5


def test_skip_locked_and_two_workers(make_bus: Callable[..., DjangoBus], hub: SyncHub) -> None:
    first, second = make_bus(delivery_batch=4), make_bus(delivery_batch=4)
    ids = publish(first, n=10)
    holder = connections.create_connection("default")
    try:
        with holder.cursor() as cur:
            cur.execute("BEGIN")
            cur.execute("SELECT id FROM rt_bus_delivery ORDER BY id LIMIT 7 FOR UPDATE")
            assert first.deliver().claimed == 3  # занятые строки пропущены, не ждём
            cur.execute("ROLLBACK")
    finally:
        holder.close()

    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def work(bus: DjangoBus) -> None:
        try:
            barrier.wait()
            for _ in range(3):
                bus.deliver()
        except BaseException as exc:  # noqa: BLE001 — передать в основной поток
            errors.append(exc)
        finally:
            connections.close_all()

    threads = [threading.Thread(target=work, args=(b,)) for b in (first, second)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    sent = [r.headers["x-rt-event-id"] for r in hub.to("crm")]
    assert sorted(sent) == sorted(ids)


def test_lease_expiry(make_bus: Callable[..., DjangoBus], clock: Clock) -> None:
    crashed, healthy = make_bus(), make_bus()
    publish(crashed)
    crashed._claim(clock(), 10)
    assert healthy.deliver().claimed == 0
    clock.advance(61)
    assert healthy.deliver().delivered == 1


def test_receiver_view_idempotent_skipped_and_auth(make_bus: Callable[..., DjangoBus]) -> None:
    registry = HandlerRegistry()
    handled: list[str] = []

    @registry.subscribe(QUOTE_SENT)
    def on_quote(event: Event) -> None:
        handled.append(event.id)
        if event.data["payload"]["erp_quote_id"] == 666:
            raise ValueError("bad quote")

    crm = make_bus("crm", registry=registry, inbox_retry_delays=())  # без автоповтора: сразу failed
    queued: list[str] = []
    crm.enqueue = queued.append
    django_support.RECEIVER.append(crm)
    client = Client()

    def post(envelope: dict[str, Any], **kw: Any) -> Any:
        headers, body = signed(envelope, **kw)
        return client.post(
            "/bus/v1/events",
            data=body,
            content_type=headers.pop("Content-Type"),
            headers=headers,
        )

    try:
        env = {**example("erp/quote.sent.v1"), "id": str(uuid.uuid4())}
        response = post(env)
        assert (response.status_code, response.json()["status"]) == (200, "received")
        assert post(env).json()["status"] == "duplicate"
        assert queued == [env["id"]]
        assert crm.process_inbox(env["id"]) == "processed"
        assert handled == [env["id"]]

        won = {**example("erp/deal.won.v1"), "id": str(uuid.uuid4())}
        assert post(won).json()["status"] == "skipped"
        assert post({**env, "id": str(uuid.uuid4())}, secret="wrong").status_code == 401
        assert client.get("/bus/v1/events").status_code == 405

        bad = {**example("erp/quote.sent.v1"), "id": str(uuid.uuid4())}
        bad["data"]["payload"]["erp_quote_id"] = 666
        post(bad)
        assert crm.process_inbox(bad["id"]) == "failed"
        [failed] = crm.list_inbox(status="failed")
        assert failed.error == "ValueError: bad quote"
        crm.enqueue = None
        registry.clear()
        registry.add(QUOTE_SENT, lambda event: handled.append("again"))
        assert crm.retry_inbox(bad["id"])
        assert [r.status for r in crm.list_inbox(event_type=QUOTE_SENT)] == ["processed", "processed"]
    finally:
        django_support.RECEIVER.pop()


def test_correlation_http_to_event_to_handler_to_log(
    make_bus: Callable[..., DjangoBus], caplog: pytest.LogCaptureFixture
) -> None:
    registry = HandlerRegistry()
    log = logging.getLogger("tests.crm.handler")
    seen: list[str | None] = []

    @registry.subscribe("uz.railtech.erp.deal.*.v1")
    def on_deal(event: Event) -> None:
        seen.append(get_correlation_id())
        log.info("deal mirrored")

    crm = make_bus("crm", registry=registry)
    client = Client()

    def forward(request: httpx.Request) -> httpx.Response:
        # доставка идёт из потока пула: приёмник CRM открывает в нём своё соединение — закрываем после запроса
        headers = {k: v for k, v in request.headers.items() if k.lower().startswith(("x-", "traceparent"))}
        try:
            response = client.post(
                "/bus/v1/events", data=request.content, content_type="application/cloudevents+json", headers=headers
            )
        finally:
            connections.close_all()
        return httpx.Response(response.status_code, content=response.content)

    erp = make_bus("erp", http=httpx.Client(transport=httpx.MockTransport(forward)))
    django_support.RECEIVER.append(crm)
    django_support.PUBLISHER.append(erp)
    try:
        response = client.post("/deals/905/win", headers={"X-Request-ID": "req-dj-1"})
        assert response["X-Request-ID"] == "req-dj-1"
        assert erp.pump().deliver.delivered == 1
        caplog.handler.addFilter(CorrelationFilter())
        with caplog.at_level(logging.INFO, logger="tests.crm.handler"):
            assert crm.requeue_stuck_inbox(older_than=-1) == 1
    finally:
        django_support.RECEIVER.pop()
        django_support.PUBLISHER.pop()
    assert seen == ["req-dj-1"]
    [record] = [r for r in caplog.records if r.getMessage() == "deal mirrored"]
    assert record.correlation_id == "req-dj-1"  # type: ignore[attr-defined]


def test_metrics_and_purge(make_bus: Callable[..., DjangoBus], hub: SyncHub, clock: Clock) -> None:
    bus = make_bus()
    publish(bus, QUOTE_SENT, n=2)
    hub.responders["crm"] = lambda r: httpx.Response(400)
    bus.deliver()
    clock.advance(30)
    metrics = bus.log_metrics()
    assert (metrics.dlq_size, metrics.outbox_pending) == (2, 0)
    assert metrics.subscribers["crm"].dead == 2
    clock.advance(86400 * 31)
    assert bus.purge() == {"deliveries": 2, "outbox": 0, "inbox": 0}


def test_secret_fields_without_stash_fail_closed(make_bus: Callable[..., DjangoBus]) -> None:
    bus = make_bus()
    with transaction.atomic(), pytest.raises(ConfigError, match="secret fields"):
        bus.publish(
            "uz.railtech.erp.quote.acceptance_code_requested.v1",
            example_data("erp/quote.acceptance_code_requested.v1"),
        )
    assert rows("SELECT id FROM rt_bus_outbox") == []


def test_delivery_refuses_outer_transaction(make_bus: Callable[..., DjangoBus], hub: SyncHub) -> None:
    bus = make_bus()
    publish(bus)
    with transaction.atomic():
        with pytest.raises(InTransactionError):
            bus.deliver()
        with pytest.raises(InTransactionError):
            bus.pump()
    assert hub.requests == []
    assert bus.deliver().delivered == 1


def test_receive_enqueues_after_outer_commit(make_bus: Callable[..., DjangoBus]) -> None:
    registry = HandlerRegistry()
    registry.add(QUOTE_SENT, lambda event: None)
    crm = make_bus("crm", registry=registry)
    queued: list[str] = []
    crm.enqueue = queued.append

    def receive_in_request(*, fail: bool) -> str:
        env = {**example("erp/quote.sent.v1"), "id": str(uuid.uuid4())}
        headers, body = signed(env)
        with transaction.atomic():  # ATOMIC_REQUESTS или транзакция вызывающего кода
            assert crm.receive(headers, body).body["status"] == "received"
            assert queued == []  # до коммита задача не ставится: она не увидела бы запись inbox
            if fail:
                raise RuntimeError("request failed")
        return str(env["id"])

    with pytest.raises(RuntimeError):
        receive_in_request(fail=True)
    assert queued == []
    assert rows("SELECT event_id FROM rt_bus_inbox") == []
    event_id = receive_in_request(fail=False)
    assert queued == [event_id]


def test_slow_response_hits_attempt_deadline(make_bus: Callable[..., DjangoBus], hub: SyncHub) -> None:
    bus = make_bus(http_timeout=0.05, attempt_deadline=0.2)
    publish(bus)
    done = threading.Event()

    def dripping(request: httpx.Request) -> httpx.Response:
        time.sleep(0.8)
        done.set()
        return httpx.Response(200)

    hub.responders["crm"] = dripping
    started = time.monotonic()
    stats = bus.deliver()
    assert time.monotonic() - started < 0.7
    assert stats.retried == 1
    assert delivery()["last_error"] == "DeadlineExceeded: no complete response within 0.2 s"
    assert done.wait(2)  # фоновый поток досчитал; его ответ не записан
    assert delivery()["status"] == "pending"


def test_inbox_autoretry(make_bus: Callable[..., DjangoBus], clock: Clock) -> None:
    registry = HandlerRegistry()
    calls: list[str] = []

    def flaky(event: Event) -> None:
        calls.append(event.id)
        if len(calls) < 3:
            raise ConnectionError("db busy")

    registry.add(QUOTE_SENT, flaky)
    crm = make_bus("crm", registry=registry, inbox_retry_delays=(30.0, 60.0))
    env = {**example("erp/quote.sent.v1"), "id": str(uuid.uuid4())}
    headers, body = signed(env)
    crm.receive(headers, body)  # без очереди: обработка — подбором
    assert crm.requeue_stuck_inbox(older_than=-1) == 1
    assert [r.status for r in crm.list_inbox()] == ["received"]
    assert crm.requeue_stuck_inbox() == 0  # срок повтора не настал
    clock.advance(37)
    assert crm.requeue_stuck_inbox() == 1
    clock.advance(73)
    assert crm.requeue_stuck_inbox() == 1
    assert [r.status for r in crm.list_inbox()] == ["processed"]
    assert len(calls) == 3
