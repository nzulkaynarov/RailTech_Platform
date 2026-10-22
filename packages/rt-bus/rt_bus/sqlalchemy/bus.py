"""`AsyncBus` — rt_bus поверх SQLAlchemy 2 `AsyncSession` (PostgreSQL; драйвер — psycopg 3 или asyncpg).

    bus = AsyncBus(BusConfig(service="crm"), sessions=async_sessionmaker(engine))
    async with sessions() as session, session.begin():
        session.add(client)
        await bus.publish(session, "uz.railtech.crm.client.updated.v1", data, subject="client/42")

Ретранслятор и доставка — `pump()` из периодической задачи (Procrastinate: `rt_bus.contrib.procrastinate`) или
`run_forever()`; приёмник — `receive()` (FastAPI: `rt_bus.fastapi.bus_router`), обработка — `process_inbox()`.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import uuid
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime, timedelta
from typing import Any, cast

import httpx
from sqlalchemy import CursorResult, TextClause, text
from sqlalchemy.ext.asyncio import AsyncSession

from .. import sql
from ..context import correlation
from ..core import (
    BusConfig,
    BusCore,
    DeliverStats,
    PumpStats,
    Statement,
    as_json,
    finish_statements,
    handler_error,
    inbox_params,
    log_outcome,
    plan_queued,
)
from ..delivery import Attempt, AttemptResult, Claimed, Outcome, decide_outcome, send_async
from ..envelope import Event
from ..errors import NotInTransactionError
from ..handlers import HandlerRegistry, default_registry
from ..journal import BusMetrics, DeliveryView, InboxView, build_metrics, log_metrics
from ..masking import AsyncSecretStash
from ..receiver import ReceiveResult, Rejection, log_rejection

logger = logging.getLogger("rt_bus")

SessionFactory = Callable[[], AsyncSession]
Enqueue = Callable[[str], Awaitable[Any]]

_TEXT: dict[str, TextClause] = {}


def _t(statement: str) -> TextClause:
    clause = _TEXT.get(statement)
    if clause is None:
        clause = _TEXT[statement] = text(statement)
    return clause


async def _exec(session: AsyncSession, statement: str, params: Mapping[str, Any] | None = None) -> Any:
    return await session.execute(_t(statement), dict(params or {}))


def _rowcount(result: Any) -> int:
    return int(cast(CursorResult[Any], result).rowcount)


class AsyncBus:
    """Шина сервиса на SQLAlchemy async: publish, ретранслятор, доставка, приёмник, inbox, журнал, метрики."""

    def __init__(
        self,
        config: BusConfig,
        sessions: SessionFactory,
        *,
        registry: HandlerRegistry | None = None,
        http: httpx.AsyncClient | None = None,
        enqueue: Enqueue | None = None,
        stash: AsyncSecretStash | None = None,
    ) -> None:
        self.core = BusCore(config)
        self.sessions = sessions
        self.registry = registry if registry is not None else default_registry
        self._http = http
        self._own_http = http is None
        self.enqueue = enqueue
        self.stash = stash

    @property
    def config(self) -> BusConfig:
        return self.core.config

    def _client(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=self.config.http_timeout, follow_redirects=False)
        return self._http

    async def aclose(self) -> None:
        if self._own_http and self._http is not None:
            await self._http.aclose()
            self._http = None

    # --- издатель -----------------------------------------------------------------------------------------------

    async def publish(
        self,
        session: AsyncSession,
        event_type: str,
        data: Mapping[str, Any],
        *,
        subject: str | None = None,
        event_id: str | uuid.UUID | None = None,
        time: datetime | None = None,
        tenant: str | None = None,
    ) -> Event:
        """Записать событие в outbox в транзакции `session`. Вне транзакции — `NotInTransactionError`;
        `data` не по схеме — `EventValidationError` (до записи)."""
        if not session.in_transaction():
            raise NotInTransactionError("rt_bus publish() needs an open transaction: use `async with session.begin()`")
        event = self.core.build_event(event_type, data, subject=subject, event_id=event_id, time=time, tenant=tenant)
        return await self._write(session, event)

    async def publish_event(self, session: AsyncSession, event: Event) -> Event:
        """Записать готовое событие (`BusCore.build_event` / `rt_bus.new_event`) — проверки те же, что у `publish`."""
        if not session.in_transaction():
            raise NotInTransactionError("rt_bus publish() needs an open transaction: use `async with session.begin()`")
        self.core.validate_outgoing(event)
        return await self._write(session, event)

    async def _write(self, session: AsyncSession, event: Event) -> Event:
        record = self.core.outbox_record(event, mask=self.stash is not None)
        if record.secrets and self.stash is not None:
            await self.stash.put(event.id, record.secrets)
        await _exec(session, sql.INSERT_OUTBOX, record.params(self.core.now()))
        logger.info("rt_bus_published", extra={"event_id": event.id, "event_type": event.type})
        return event

    # --- ретранслятор: раскладка outbox по подписчикам ------------------------------------------------------------

    async def relay(self, limit: int | None = None) -> int:
        """Разложить пачку outbox (`FOR UPDATE SKIP LOCKED`): по строке доставки на подписчика.

        Возвращает число разложенных строк outbox."""
        now = self.core.now()
        async with self.sessions() as session, session.begin():
            rows = (
                (await _exec(session, sql.CLAIM_OUTBOX, {"limit": limit or self.config.relay_batch})).mappings().all()
            )
            for row in rows:
                for subscriber in self.core.targets(row["type"], row["source"]):
                    await _exec(
                        session,
                        sql.INSERT_DELIVERY,
                        {"event_id": row["id"], "event_type": row["type"], "subscriber": subscriber.name, "now": now},
                    )
                await _exec(session, sql.MARK_DISPATCHED, {"id": row["id"], "now": now})
        return len(rows)

    # --- доставка ------------------------------------------------------------------------------------------------

    async def _claim(self, now: datetime, limit: int) -> list[tuple[Claimed, dict[str, Any] | None]]:
        breaker = self.config.breaker
        lease_until = now + timedelta(seconds=self.config.lease_seconds)
        token = uuid.uuid4()
        picked: list[tuple[int, bool]] = []
        out: list[tuple[Claimed, dict[str, Any] | None]] = []
        async with self.sessions() as session, session.begin():
            states = (await _exec(session, sql.PAUSED_STATES)).mappings().all()
            blocked = [r["subscriber"] for r in states if r["paused_until"] > now]
            half_open = [
                r for r in states if r["paused_until"] <= now and r["consecutive_failures"] >= breaker.threshold
            ]
            for state in half_open:
                slot = (
                    await _exec(
                        session,
                        sql.TAKE_PROBE_SLOT,
                        {
                            "probe_until": lease_until,
                            "now": now,
                            "subscriber": state["subscriber"],
                            "threshold": breaker.threshold,
                        },
                    )
                ).first()
                if slot is None:
                    continue
                probe = (await _exec(session, sql.CLAIM_PROBE, {"now": now, "subscriber": state["subscriber"]})).first()
                if probe is None:
                    await _exec(
                        session,
                        sql.RESTORE_PROBE_SLOT,
                        {"paused_until": state["paused_until"], "subscriber": state["subscriber"]},
                    )
                    continue
                picked.append((int(probe[0]), True))
            excluded = blocked + [r["subscriber"] for r in half_open]
            if limit > len(picked):
                rows = (
                    await _exec(
                        session, sql.CLAIM_DELIVERIES, {"now": now, "excluded": excluded, "limit": limit - len(picked)}
                    )
                ).all()
                picked.extend((int(r[0]), False) for r in rows)
            envelopes: dict[uuid.UUID, dict[str, Any] | None] = {}
            for delivery_id, is_probe in picked:
                row = (
                    (
                        await _exec(
                            session,
                            sql.LEASE_DELIVERY,
                            {"id": delivery_id, "lease_until": lease_until, "token": token, "now": now},
                        )
                    )
                    .mappings()
                    .one()
                )
                claimed = Claimed(
                    id=row["id"],
                    event_id=row["event_id"],
                    event_type=row["event_type"],
                    subscriber=row["subscriber"],
                    attempts=row["attempts"],
                    lease_token=token,
                    probe=is_probe,
                )
                if claimed.event_id not in envelopes:
                    env = (await _exec(session, sql.SELECT_ENVELOPE, {"id": claimed.event_id})).first()
                    envelopes[claimed.event_id] = None if env is None else as_json(env[0])
                out.append((claimed, envelopes[claimed.event_id]))
        return out

    async def deliver(self, limit: int | None = None) -> DeliverStats:
        """Взять пачку готовых доставок в аренду, отправить параллельно, записать итоги. HTTP — вне транзакций."""
        stats = DeliverStats()
        now = self.core.now()
        claimed = await self._claim(now, limit or self.config.delivery_batch)
        if not claimed:
            return stats
        stats.claimed = len(claimed)
        stash_enabled = self.stash is not None
        planned: list[tuple[Claimed, Attempt | Outcome]] = []
        for item, envelope in claimed:
            secret_values = None
            if stash_enabled and self.stash is not None and self.core.needs_stash(item.event_type):
                secret_values = await self.stash.get(str(item.event_id))
            planned.append((item, self.core.plan(item, envelope, secret_values, stash_enabled=stash_enabled, now=now)))

        async def run(attempt: Attempt) -> AttemptResult:
            return await send_async(self._client(), attempt, self.config.http_timeout, self.core.now())

        sends = [run(p) for _, p in planned if isinstance(p, Attempt)]
        results = iter(await asyncio.gather(*sends))
        finished_at = self.core.now()
        outcomes: list[tuple[Claimed, Outcome]] = []
        for item, plan in planned:
            if isinstance(plan, Attempt):
                outcome = decide_outcome(
                    item, next(results), policy=self.config.retry, now=finished_at, rng=self.config.rng
                )
            else:
                outcome = plan
            outcomes.append((item, outcome))
        async with self.sessions() as session, session.begin():
            for item, outcome in outcomes:
                await self._record(session, item, outcome, finished_at, stats)
        return stats

    async def _record(
        self, session: AsyncSession, item: Claimed, outcome: Outcome, now: datetime, stats: DeliverStats
    ) -> None:
        finish, breaker = finish_statements(self.core, item, outcome, now)
        if _rowcount(await _exec(session, finish.sql, finish.params)) == 0:
            stats.lost_lease += 1
            logger.warning("rt_bus_lease_lost", extra={"delivery_id": item.id, "subscriber": item.subscriber})
            return
        stats.count(outcome)
        failures = await self._breaker(session, breaker)
        log_outcome(item, outcome, failures, self.config.breaker.threshold)

    async def _breaker(self, session: AsyncSession, statement: Statement | None) -> int | None:
        if statement is None:
            return None
        result = await _exec(session, statement.sql, statement.params)
        if statement.sql is sql.BREAKER_FAILURE:
            return int(result.first()[0])
        return None

    async def pump(self, *, max_seconds: float = 20.0) -> PumpStats:
        """Раскладка outbox и доставка, пока есть работа (не дольше `max_seconds`) — тело периодической задачи."""
        stats = PumpStats()
        deadline = time.monotonic() + max_seconds
        while time.monotonic() < deadline:
            relayed = await self.relay()
            stats.relayed += relayed
            if relayed < self.config.relay_batch:
                break
        while time.monotonic() < deadline:
            step = await self.deliver()
            for name in ("claimed", "delivered", "retried", "dead", "postponed", "lost_lease"):
                setattr(stats.deliver, name, getattr(stats.deliver, name) + getattr(step, name))
            if step.claimed < self.config.delivery_batch:
                break
        return stats

    async def run_forever(self, *, interval: float = 2.0, stop: asyncio.Event | None = None) -> None:
        """Цикл `pump()` каждые `interval` секунд до `stop` (фоновая задача lifespan, если очереди нет)."""
        stop = stop or asyncio.Event()
        while not stop.is_set():
            try:
                await self.pump()
            except Exception:
                logger.exception("rt_bus_pump_failed")
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=interval)

    # --- ручное и журнал -------------------------------------------------------------------------------------------

    async def retry_delivery(self, delivery_id: int) -> bool:
        """«Повторить»: доставка `dead` (или ожидающая) — сейчас, попытки с нуля; пауза предохранителя → проба."""
        now = self.core.now()
        async with self.sessions() as session, session.begin():
            row = (await _exec(session, sql.RETRY_DELIVERY, {"id": delivery_id, "now": now})).first()
            if row is not None:
                await _exec(session, sql.PROBE_NOW, {"subscribers": [row[1]], "now": now})
        if row is not None:
            logger.info("rt_bus_delivery_retry_manual", extra={"delivery_id": delivery_id})
        return row is not None

    async def retry_all_dead(self, subscriber: str | None = None) -> int:
        """«Повторить все dead» (по подписчику или все)."""
        now = self.core.now()
        async with self.sessions() as session, session.begin():
            rows = (await _exec(session, sql.RETRY_ALL_DEAD, {"subscriber": subscriber, "now": now})).all()
            if rows:
                await _exec(session, sql.PROBE_NOW, {"subscribers": sorted({r[1] for r in rows}), "now": now})
        logger.info("rt_bus_dead_retry_manual", extra={"subscriber": subscriber, "count": len(rows)})
        return len(rows)

    async def list_deliveries(
        self,
        *,
        status: str | None = None,
        subscriber: str | None = None,
        event_type: str | None = None,
        event_id: str | uuid.UUID | None = None,
        before_id: int | None = None,
        limit: int = 50,
    ) -> list[DeliveryView]:
        params = {
            "status": status,
            "subscriber": subscriber,
            "event_type": event_type,
            "event_id": None if event_id is None else uuid.UUID(str(event_id)),
            "before_id": before_id,
            "limit": limit,
        }
        async with self.sessions() as session:
            rows = (await _exec(session, sql.LIST_DELIVERIES, params)).mappings().all()
        return [DeliveryView.from_row(r) for r in rows]

    # --- приёмник и inbox ----------------------------------------------------------------------------------------

    async def receive(self, headers: Mapping[str, str], body: bytes) -> ReceiveResult:
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
                async with self.sessions() as session, session.begin():
                    inserted = (await _exec(session, sql.INSERT_INBOX, inbox_params(decision, now))).first()
                    if inserted is None:
                        logger.info("rt_bus_receive_duplicate", extra={"event_id": event.id})
                        return ReceiveResult(200, {"status": "duplicate", "id": event.id})
                    for handler in decision.inline:
                        await handler.func(event, session)
                    if decision.inline and not decision.queued:
                        status = sql.PROCESSED
                        await _exec(
                            session,
                            sql.FINISH_INBOX,
                            {"event_id": uuid.UUID(event.id), "status": status, "error": None, "now": now},
                        )
            except Exception:
                logger.exception("rt_bus_inline_handler_failed", extra={"event_id": event.id, "event_type": event.type})
                return ReceiveResult(503, {"error": "handler_failed"})
            logger.info("rt_bus_received", extra={"event_id": event.id, "event_type": event.type, "status": status})
            if status == sql.RECEIVED:
                await self._enqueue(event.id)
        return ReceiveResult(200, {"status": status, "id": event.id})

    async def _enqueue(self, event_id: str) -> None:
        if self.enqueue is None:
            return
        try:
            await self.enqueue(event_id)
        except Exception:
            # Запись inbox уже в базе: её подберёт requeue_stuck_inbox.
            logger.exception("rt_bus_enqueue_failed", extra={"event_id": event_id})

    async def process_inbox(self, event_id: str | uuid.UUID) -> str | None:
        """Задача очереди: обработать запись inbox. Возвращает итоговый статус (`None` — нет записи или она занята)."""
        key = uuid.UUID(str(event_id))
        async with self.sessions() as session:
            event: Event | None = None
            try:
                async with session.begin():
                    row = (await _exec(session, sql.LOCK_INBOX, {"event_id": key})).mappings().first()
                    if row is None:
                        return None
                    if row["status"] != sql.RECEIVED:
                        return str(row["status"])
                    event = Event.from_dict(as_json(row["envelope"]))
                    with correlation(event.correlationid, event.traceparent):
                        plan = plan_queued(self.core, self.registry, event)
                        for handler in plan.handlers:
                            await handler.func(event, session)
                        status = plan.status or sql.PROCESSED
                        await _exec(
                            session,
                            sql.FINISH_INBOX,
                            {"event_id": key, "status": status, "error": plan.error, "now": self.core.now()},
                        )
                        logger.info("rt_bus_processed", extra={"event_id": str(key), "status": status})
                        return status
            except Exception as exc:
                with correlation(event.correlationid if event else None, event.traceparent if event else None):
                    logger.exception("rt_bus_handler_failed", extra={"event_id": str(key)})
                async with session.begin():
                    await _exec(
                        session, sql.FAIL_INBOX, {"event_id": key, "error": handler_error(exc), "now": self.core.now()}
                    )
                return sql.FAILED

    async def retry_inbox(self, event_id: str | uuid.UUID) -> bool:
        """«Повторить» запись inbox `failed`/`skipped`: снова `received` и в очередь."""
        key = uuid.UUID(str(event_id))
        async with self.sessions() as session, session.begin():
            row = (await _exec(session, sql.RETRY_INBOX, {"event_id": key, "now": self.core.now()})).first()
        if row is None:
            return False
        if self.enqueue is None:
            await self.process_inbox(key)
        else:
            await self._enqueue(str(key))
        return True

    async def requeue_stuck_inbox(self, *, older_than: float = 60.0, limit: int = 100) -> int:
        """Записи `received`, которых не взяла очередь (сбой постановки), — снова в очередь (или обработать здесь)."""
        before = self.core.now() - timedelta(seconds=older_than)
        async with self.sessions() as session:
            rows = (await _exec(session, sql.STUCK_INBOX, {"before": before, "limit": limit})).all()
        for row in rows:
            if self.enqueue is None:
                await self.process_inbox(row[0])
            else:
                await self._enqueue(str(row[0]))
        return len(rows)

    async def list_inbox(
        self,
        *,
        status: str | None = None,
        event_type: str | None = None,
        before: datetime | None = None,
        limit: int = 50,
    ) -> list[InboxView]:
        params = {"status": status, "event_type": event_type, "before": before, "limit": limit}
        async with self.sessions() as session:
            rows = (await _exec(session, sql.LIST_INBOX, params)).mappings().all()
        return [InboxView.from_row(r) for r in rows]

    # --- метрики и уборка ------------------------------------------------------------------------------------------

    async def metrics(self) -> BusMetrics:
        async with self.sessions() as session:
            outbox = (await _exec(session, sql.METRICS_OUTBOX)).mappings().first()
            deliveries = (await _exec(session, sql.METRICS_DELIVERY)).mappings().all()
            states = (await _exec(session, sql.METRICS_STATE)).mappings().all()
            inbox = (await _exec(session, sql.METRICS_INBOX)).mappings().all()
        return build_metrics(self.core.now(), outbox, deliveries, states, inbox)

    async def log_metrics(self) -> BusMetrics:
        metrics = await self.metrics()
        log_metrics(self.config.service, metrics)
        return metrics

    async def purge(self, older_than: timedelta = timedelta(days=30)) -> dict[str, int]:
        """Удалить доставленное, разложенное без доставок и обработанное старше `older_than` (`dead` остаётся)."""
        before = self.core.now() - older_than
        async with self.sessions() as session, session.begin():
            deliveries = _rowcount(await _exec(session, sql.PURGE_DELIVERIES, {"before": before}))
            outbox = _rowcount(await _exec(session, sql.PURGE_OUTBOX, {"before": before}))
            inbox = _rowcount(await _exec(session, sql.PURGE_INBOX, {"before": before}))
        return {"deliveries": deliveries, "outbox": outbox, "inbox": inbox}
