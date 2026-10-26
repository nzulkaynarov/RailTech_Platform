"""`DjangoBus` — rt_bus поверх Django ORM-соединения (ERP: Django + Celery, psycopg2 или psycopg 3).

    bus = DjangoBus(BusConfig(service="erp"), stash=DjangoCacheStash())
    with transaction.atomic():
        quote.save()
        bus.publish("uz.railtech.erp.quote.sent.v1", data, subject=deal.number)

Ретранслятор и доставка — `pump()` из задачи Celery (`rt_bus.contrib.celery`); приёмник — `bus_view(bus)`;
обработка записи inbox — `process_inbox()` в задаче Celery.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from functools import partial
from typing import Any

import httpx
from django.db import connections, transaction
from django.db.backends.utils import CursorWrapper

from .. import sql
from ..context import correlation
from ..core import (
    RECORD_ATTEMPTS,
    BusConfig,
    BusCore,
    DeliverStats,
    PumpStats,
    Statement,
    as_json,
    finish_statements,
    handler_error,
    inbox_params,
    inbox_retry_at,
    log_outcome,
    plan_queued,
    record_groups,
    retryable_db_error,
)
from ..delivery import Attempt, AttemptResult, Claimed, Outcome, deadline_result, decide_outcome, send_sync
from ..envelope import Event
from ..errors import InTransactionError, NotInTransactionError
from ..handlers import HandlerRegistry, default_registry
from ..journal import BusMetrics, DeliveryView, InboxView, build_metrics, log_metrics
from ..masking import SecretStash
from ..receiver import ReceiveResult, Rejection, log_rejection

logger = logging.getLogger("rt_bus")

Enqueue = Callable[[str], Any]


def _rows(cursor: CursorWrapper) -> list[dict[str, Any]]:
    if cursor.description is None:
        return []
    names = [col[0] for col in cursor.description]
    return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]


class DjangoBus:
    """Шина сервиса на Django: publish, ретранслятор, доставка, приёмник, inbox, журнал, метрики."""

    def __init__(
        self,
        config: BusConfig,
        *,
        registry: HandlerRegistry | None = None,
        http: httpx.Client | None = None,
        enqueue: Enqueue | None = None,
        stash: SecretStash | None = None,
        wakeup: Callable[[], Any] | None = None,
        using: str = "default",
    ) -> None:
        self.core = BusCore(config)
        self.registry = registry if registry is not None else default_registry
        self._http = http
        self.enqueue = enqueue
        self.stash = stash
        self.wakeup = wakeup
        self.using = using

    @property
    def config(self) -> BusConfig:
        return self.core.config

    def _client(self) -> httpx.Client:
        if self._http is None:
            self._http = httpx.Client(timeout=self.config.http_timeout, follow_redirects=False)
        return self._http

    def _exec(self, statement: str, params: Mapping[str, Any] | None = None) -> tuple[list[dict[str, Any]], int]:
        with connections[self.using].cursor() as cursor:
            cursor.execute(sql.pyformat(statement), dict(params or {}))
            return _rows(cursor), cursor.rowcount

    def _atomic(self) -> transaction.Atomic:
        return transaction.atomic(using=self.using)

    # --- издатель -----------------------------------------------------------------------------------------------

    def publish(
        self,
        event_type: str,
        data: Mapping[str, Any],
        *,
        subject: str | None = None,
        event_id: str | uuid.UUID | None = None,
        time: datetime | None = None,
        tenant: str | None = None,
    ) -> Event:
        """Записать событие в outbox в текущей транзакции (`transaction.atomic`). Вне транзакции —
        `NotInTransactionError`; `data` не по схеме — `EventValidationError` (до записи)."""
        self._require_atomic()
        event = self.core.build_event(event_type, data, subject=subject, event_id=event_id, time=time, tenant=tenant)
        return self._write(event)

    def publish_event(self, event: Event) -> Event:
        """Записать готовое событие (`BusCore.build_event` / `rt_bus.new_event`) — проверки те же, что у `publish`."""
        self._require_atomic()
        self.core.validate_outgoing(event)
        return self._write(event)

    def _write(self, event: Event) -> Event:
        record = self.core.outbox_record(event, stash_enabled=self.stash is not None)
        if record.secrets and self.stash is not None:
            self.stash.put(event.id, record.secrets)
        self._exec(sql.INSERT_OUTBOX, record.params(self.core.now()))
        self._arm_wakeup()
        logger.info("rt_bus_published", extra={"event_id": event.id, "event_type": event.type})
        return event

    def _require_atomic(self) -> None:
        if not transaction.get_connection(self.using).in_atomic_block:
            raise NotInTransactionError("rt_bus publish() needs transaction.atomic()")

    def _forbid_atomic(self, what: str) -> None:
        if transaction.get_connection(self.using).in_atomic_block:
            raise InTransactionError(f"rt_bus {what}() must not run inside transaction.atomic(): HTTP goes outside")

    def _arm_wakeup(self) -> None:
        """После коммита внешней транзакции — одно пробуждение на сколько угодно `publish` в ней.

        Повтор определяем по очереди `run_on_commit` соединения: откат точки сохранения убирает её записи, поэтому
        `publish` из отменённого блока не оставляет «лишней» отметки. Изменился внутренний формат Django — просто
        получим по пробуждению на `publish` (тест дедупликации это поймает)."""
        if self.wakeup is None:
            return
        queued = getattr(transaction.get_connection(self.using), "run_on_commit", ())
        if any(entry[1] == self._wake for entry in queued):
            return
        transaction.on_commit(self._wake, using=self.using)

    def _wake(self) -> None:
        try:
            if self.wakeup is not None:
                self.wakeup()
        except Exception:
            logger.exception("rt_bus_wakeup_failed")

    # --- ретранслятор ----------------------------------------------------------------------------------------------

    def relay(self, limit: int | None = None) -> int:
        """Разложить пачку outbox (`FOR UPDATE SKIP LOCKED`): по строке доставки на подписчика."""
        now = self.core.now()
        with self._atomic():
            rows, _ = self._exec(sql.CLAIM_OUTBOX, {"limit": limit or self.config.relay_batch})
            for row in rows:
                for subscriber in self.core.targets(row["type"], row["source"]):
                    self._exec(
                        sql.INSERT_DELIVERY,
                        {"event_id": row["id"], "event_type": row["type"], "subscriber": subscriber.name, "now": now},
                    )
                self._exec(sql.MARK_DISPATCHED, {"id": row["id"], "now": now})
        return len(rows)

    # --- доставка ------------------------------------------------------------------------------------------------

    def _claim(self, now: datetime, limit: int) -> list[tuple[Claimed, dict[str, Any] | None]]:
        breaker = self.config.breaker
        lease_until = now + timedelta(seconds=self.config.lease_seconds)
        token = uuid.uuid4()
        picked: list[tuple[int, bool]] = []
        out: list[tuple[Claimed, dict[str, Any] | None]] = []
        with self._atomic():
            states, _ = self._exec(sql.PAUSED_STATES)
            blocked = [r["subscriber"] for r in states if r["paused_until"] > now]
            # выключенный подписчик (enabled: false): уже разложенные доставки ждут включения, не уходят и не пробуются
            disabled = self.core.disabled_subscribers()
            half_open = [
                r
                for r in states
                if r["paused_until"] <= now
                and r["consecutive_failures"] >= breaker.threshold
                and r["subscriber"] not in disabled
            ]
            for state in half_open:
                slot, _ = self._exec(
                    sql.TAKE_PROBE_SLOT,
                    {
                        "probe_until": lease_until,
                        "now": now,
                        "subscriber": state["subscriber"],
                        "threshold": breaker.threshold,
                    },
                )
                if not slot:
                    continue
                probe, _ = self._exec(sql.CLAIM_PROBE, {"now": now, "subscriber": state["subscriber"]})
                if not probe:
                    self._exec(
                        sql.RESTORE_PROBE_SLOT,
                        {"paused_until": state["paused_until"], "subscriber": state["subscriber"]},
                    )
                    continue
                picked.append((int(probe[0]["id"]), True))
            excluded = blocked + [r["subscriber"] for r in half_open] + disabled
            if limit > len(picked):
                rows, _ = self._exec(
                    sql.CLAIM_DELIVERIES, {"now": now, "excluded": excluded, "limit": limit - len(picked)}
                )
                picked.extend((int(r["id"]), False) for r in rows)
            envelopes: dict[uuid.UUID, dict[str, Any] | None] = {}
            for delivery_id, is_probe in picked:
                leased, _ = self._exec(
                    sql.LEASE_DELIVERY, {"id": delivery_id, "lease_until": lease_until, "token": token, "now": now}
                )
                row = leased[0]
                claimed = Claimed(
                    id=row["id"],
                    event_id=uuid.UUID(str(row["event_id"])),
                    event_type=row["event_type"],
                    subscriber=row["subscriber"],
                    attempts=row["attempts"],
                    lease_token=token,
                    probe=is_probe,
                )
                if claimed.event_id not in envelopes:
                    env, _ = self._exec(sql.SELECT_ENVELOPE, {"id": claimed.event_id})
                    envelopes[claimed.event_id] = as_json(env[0]["envelope"]) if env else None
                out.append((claimed, envelopes[claimed.event_id]))
        return out

    def deliver(self, limit: int | None = None) -> DeliverStats:
        """Взять пачку доставок в аренду, отправить параллельно (потоки), записать итоги. HTTP — вне транзакций:
        внутри `transaction.atomic()` — `InTransactionError`."""
        self._forbid_atomic("deliver")
        stats = DeliverStats()
        now = self.core.now()
        claimed = self._claim(now, limit or self.config.delivery_batch)
        if not claimed:
            return stats
        stats.claimed = len(claimed)
        stash_enabled = self.stash is not None
        planned: list[tuple[Claimed, Attempt | Outcome]] = []
        for item, envelope in claimed:
            secret_values = None
            if self.stash is not None and self.core.needs_stash(item.event_type):
                secret_values = self.stash.get(str(item.event_id))
            planned.append((item, self.core.plan(item, envelope, secret_values, stash_enabled=stash_enabled, now=now)))
        attempts = [p for _, p in planned if isinstance(p, Attempt)]
        client = self._client()

        def run(attempt: Attempt) -> AttemptResult:
            return send_sync(client, attempt, self.config.http_timeout, self.core.now())

        results: list[AttemptResult] = []
        if attempts:
            # Общий дедлайн попытки (меньше аренды): поток с зависшим ответом не держит пачку — итог «повтор»,
            # поток досчитает в фоне (его результат уже не пишется: доставка снова pending).
            pool = ThreadPoolExecutor(max_workers=min(len(attempts), self.config.delivery_batch))
            futures = [pool.submit(run, attempt) for attempt in attempts]
            deadline = time.monotonic() + self.config.attempt_deadline
            for future in futures:
                try:
                    results.append(future.result(timeout=max(deadline - time.monotonic(), 0.0)))
                except TimeoutError:
                    results.append(deadline_result(self.config.attempt_deadline))
            pool.shutdown(wait=False, cancel_futures=True)
        result_iter = iter(results)
        finished_at = self.core.now()
        outcomes: list[tuple[Claimed, Outcome]] = []
        for item, plan in planned:
            outcome = (
                decide_outcome(item, next(result_iter), policy=self.config.retry, now=finished_at, rng=self.config.rng)
                if isinstance(plan, Attempt)
                else plan
            )
            outcomes.append((item, outcome))
        self._record_all(outcomes, finished_at, stats)
        return stats

    def _record_all(self, outcomes: list[tuple[Claimed, Outcome]], now: datetime, stats: DeliverStats) -> None:
        """Итоги по подписчикам в порядке имён, по короткой транзакции на подписчика (W11B-G-1): параллельные `pump`
        не блокируют друг друга на `rt_bus_subscriber_state`, а сбой одной группы не держит аренду чужих — остальные
        группы записываются, ошибка поднимается в конце."""
        failure: Exception | None = None
        for group in record_groups(outcomes):
            try:
                self._record_group(group, now, stats)
            except Exception as exc:
                logger.exception("rt_bus_record_failed", extra={"subscriber": group[0][0].subscriber})
                failure = failure or exc
        if failure is not None:
            raise failure

    def _record_group(self, group: list[tuple[Claimed, Outcome]], now: datetime, stats: DeliverStats) -> None:
        for attempt in range(1, RECORD_ATTEMPTS + 1):
            local = DeliverStats()
            try:
                with self._atomic():
                    for item, outcome in group:
                        self._record(item, outcome, now, local)
            except Exception as exc:
                if attempt == RECORD_ATTEMPTS or not retryable_db_error(exc):
                    raise
                logger.warning("rt_bus_record_retry", extra={"subscriber": group[0][0].subscriber, "attempt": attempt})
                time.sleep(0.05 * attempt * (1.0 + self.config.rng.random()))
                continue
            stats.merge(local)
            return

    def _record(self, item: Claimed, outcome: Outcome, now: datetime, stats: DeliverStats) -> None:
        finish, breaker = finish_statements(self.core, item, outcome, now)
        _, count = self._exec(finish.sql, finish.params)
        if count == 0:
            stats.lost_lease += 1
            logger.warning("rt_bus_lease_lost", extra={"delivery_id": item.id, "subscriber": item.subscriber})
            return
        stats.count(outcome)
        log_outcome(item, outcome, self._breaker(breaker, item, now, stats), self.config.breaker.threshold)

    def _breaker(self, statement: Statement | None, item: Claimed, now: datetime, stats: DeliverStats) -> int | None:
        if statement is None:
            return None
        rows, _ = self._exec(statement.sql, statement.params)
        if statement.sql is sql.BREAKER_FAILURE:
            return int(rows[0]["consecutive_failures"])
        if statement.sql is sql.BREAKER_SUCCESS and int(rows[0]["previous_failures"]) >= self.config.breaker.threshold:
            # Подписчик восстановился (C1-G-6): накопленные повторы уходят сразу, а не по расписанию.
            _, reset = self._exec(sql.RESET_BACKLOG, {"subscriber": item.subscriber, "now": now})
            stats.recovered += 1
            logger.info("rt_bus_subscriber_recovered", extra={"subscriber": item.subscriber, "reset": reset})
        return None

    def pump(self, *, max_seconds: float = 20.0) -> PumpStats:
        """Раскладка outbox и доставка, пока есть работа (не дольше `max_seconds`) — тело задачи Celery."""
        self._forbid_atomic("pump")
        stats = PumpStats()
        deadline = time.monotonic() + max_seconds
        while time.monotonic() < deadline:
            relayed = self.relay()
            stats.relayed += relayed
            if relayed < self.config.relay_batch:
                break
        while time.monotonic() < deadline:
            step = self.deliver()
            stats.deliver.merge(step)
            if step.claimed < self.config.delivery_batch and not step.recovered:
                break
        return stats

    # --- ручное и журнал -------------------------------------------------------------------------------------------

    def retry_delivery(self, delivery_id: int) -> bool:
        """«Повторить»: доставка `dead` (или ожидающая) — сейчас, попытки с нуля; пауза предохранителя → проба."""
        now = self.core.now()
        with self._atomic():
            rows, _ = self._exec(sql.RETRY_DELIVERY, {"id": delivery_id, "now": now})
            if rows:
                self._exec(sql.PROBE_NOW, {"subscribers": [rows[0]["subscriber"]], "now": now})
        if rows:
            logger.info("rt_bus_delivery_retry_manual", extra={"delivery_id": delivery_id})
        return bool(rows)

    def retry_all_dead(self, subscriber: str | None = None) -> int:
        now = self.core.now()
        with self._atomic():
            rows, _ = self._exec(sql.RETRY_ALL_DEAD, {"subscriber": subscriber, "now": now})
            if rows:
                self._exec(sql.PROBE_NOW, {"subscribers": sorted({r["subscriber"] for r in rows}), "now": now})
        logger.info("rt_bus_dead_retry_manual", extra={"subscriber": subscriber, "count": len(rows)})
        return len(rows)

    def list_deliveries(
        self,
        *,
        status: str | None = None,
        subscriber: str | None = None,
        event_type: str | None = None,
        event_id: str | uuid.UUID | None = None,
        before_id: int | None = None,
        limit: int = 50,
    ) -> list[DeliveryView]:
        rows, _ = self._exec(
            sql.LIST_DELIVERIES,
            {
                "status": status,
                "subscriber": subscriber,
                "event_type": event_type,
                "event_id": None if event_id is None else uuid.UUID(str(event_id)),
                "before_id": before_id,
                "limit": limit,
            },
        )
        return [DeliveryView.from_row(_uuid_fields(r, "event_id")) for r in rows]

    # --- приёмник и inbox ----------------------------------------------------------------------------------------

    def receive(self, headers: Mapping[str, str], body: bytes) -> ReceiveResult:
        """Принять доставку: проверка → inbox (повтор `id` — 200 без обработки) → inline-обработчики → очередь."""
        decision = self.core.decide(self.registry, headers, body)
        if isinstance(decision, Rejection):
            log_rejection(decision, headers)
            return decision.result()
        event = decision.event
        now = self.core.now()
        status: str = decision.status
        with correlation(event.correlationid, event.traceparent):
            try:
                with self._atomic():
                    inserted, _ = self._exec(sql.INSERT_INBOX, inbox_params(decision, now))
                    if not inserted:
                        logger.info("rt_bus_receive_duplicate", extra={"event_id": event.id})
                        return ReceiveResult(200, {"status": "duplicate", "id": event.id})
                    for handler in decision.inline:
                        handler.func(event)
                    if decision.inline and not decision.queued:
                        status = sql.PROCESSED
                        self._exec(
                            sql.FINISH_INBOX,
                            {"event_id": uuid.UUID(event.id), "status": status, "error": None, "now": now},
                        )
            except Exception:
                logger.exception("rt_bus_inline_handler_failed", extra={"event_id": event.id, "event_type": event.type})
                return ReceiveResult(503, {"error": "handler_failed"})
            logger.info("rt_bus_received", extra={"event_id": event.id, "event_type": event.type, "status": status})
            if status == sql.RECEIVED:
                # После коммита внешней транзакции (ATOMIC_REQUESTS и т. п.); без неё — сразу.
                transaction.on_commit(partial(self._enqueue, event.id), using=self.using)
        return ReceiveResult(200, {"status": status, "id": event.id})

    def _enqueue(self, event_id: str) -> None:
        if self.enqueue is None:
            return
        try:
            self.enqueue(event_id)
        except Exception:
            logger.exception("rt_bus_enqueue_failed", extra={"event_id": event_id})

    def process_inbox(self, event_id: str | uuid.UUID) -> str | None:
        """Задача очереди: обработать запись inbox. Возвращает итоговый статус (`None` — нет записи или она занята)."""
        key = uuid.UUID(str(event_id))
        event: Event | None = None
        try:
            with self._atomic():
                rows, _ = self._exec(sql.LOCK_INBOX, {"event_id": key})
                if not rows:
                    return None
                row = rows[0]
                if row["status"] != sql.RECEIVED:
                    return str(row["status"])
                if row["next_attempt_at"] is not None and row["next_attempt_at"] > self.core.now():
                    return sql.RECEIVED  # ждёт автоповтора — раньше срока не обрабатываем
                event = Event.from_dict(as_json(row["envelope"]))
                with correlation(event.correlationid, event.traceparent):
                    plan = plan_queued(self.core, self.registry, event)
                    for handler in plan.handlers:
                        handler.func(event)
                    status = plan.status or sql.PROCESSED
                    self._exec(
                        sql.FINISH_INBOX,
                        {"event_id": key, "status": status, "error": plan.error, "now": self.core.now()},
                    )
                    logger.info("rt_bus_processed", extra={"event_id": str(key), "status": status})
                    return status
        except Exception as exc:
            with correlation(event.correlationid if event else None, event.traceparent if event else None):
                logger.exception("rt_bus_handler_failed", extra={"event_id": str(key)})
            now = self.core.now()
            with self._atomic():
                bumped, _ = self._exec(sql.INBOX_FAILURE, {"event_id": key, "error": handler_error(exc), "now": now})
                if not bumped:
                    return None
                retry_at = inbox_retry_at(self.core, int(bumped[0]["attempts"]), now)
                if retry_at is not None:
                    self._exec(sql.INBOX_RETRY_LATER, {"event_id": key, "next_attempt_at": retry_at})
                    return sql.RECEIVED
                self._exec(sql.INBOX_FAILED, {"event_id": key})
            return sql.FAILED

    def retry_inbox(self, event_id: str | uuid.UUID) -> bool:
        key = uuid.UUID(str(event_id))
        with self._atomic():
            rows, _ = self._exec(sql.RETRY_INBOX, {"event_id": key, "now": self.core.now()})
        if not rows:
            return False
        if self.enqueue is None:
            self.process_inbox(key)
        else:
            transaction.on_commit(partial(self._enqueue, str(key)), using=self.using)
        return True

    def requeue_stuck_inbox(self, *, older_than: float = 60.0, limit: int = 100) -> int:
        """Записи `received`, не взятые очередью, и автоповторы, чей срок настал, — снова в очередь (после коммита)."""
        now = self.core.now()
        before = now - timedelta(seconds=older_than)
        with self._atomic():
            rows, _ = self._exec(sql.STUCK_INBOX, {"before": before, "now": now, "limit": limit})
        for row in rows:
            if self.enqueue is None:
                self.process_inbox(row["event_id"])
            else:
                transaction.on_commit(partial(self._enqueue, str(row["event_id"])), using=self.using)
        return len(rows)

    def list_inbox(
        self,
        *,
        status: str | None = None,
        event_type: str | None = None,
        before: datetime | None = None,
        limit: int = 50,
    ) -> list[InboxView]:
        rows, _ = self._exec(
            sql.LIST_INBOX, {"status": status, "event_type": event_type, "before": before, "limit": limit}
        )
        return [InboxView.from_row(_uuid_fields(r, "event_id")) for r in rows]

    # --- метрики и уборка ------------------------------------------------------------------------------------------

    def metrics(self) -> BusMetrics:
        outbox, _ = self._exec(sql.METRICS_OUTBOX)
        deliveries, _ = self._exec(sql.METRICS_DELIVERY)
        states, _ = self._exec(sql.METRICS_STATE)
        inbox, _ = self._exec(sql.METRICS_INBOX)
        return build_metrics(
            self.core.now(),
            outbox[0] if outbox else None,
            deliveries,
            states,
            inbox,
            disabled=self.core.disabled_subscribers(),
        )

    def log_metrics(self) -> BusMetrics:
        metrics = self.metrics()
        log_metrics(self.config.service, metrics)
        return metrics

    def purge(self, older_than: timedelta = timedelta(days=30)) -> dict[str, int]:
        before = self.core.now() - older_than
        with self._atomic():
            _, deliveries = self._exec(sql.PURGE_DELIVERIES, {"before": before})
            _, outbox = self._exec(sql.PURGE_OUTBOX, {"before": before})
            _, inbox = self._exec(sql.PURGE_INBOX, {"before": before})
        return {"deliveries": deliveries, "outbox": outbox, "inbox": inbox}


def _uuid_fields(row: dict[str, Any], *names: str) -> dict[str, Any]:
    for name in names:
        if row.get(name) is not None and not isinstance(row[name], uuid.UUID):
            row[name] = uuid.UUID(str(row[name]))
    return row
