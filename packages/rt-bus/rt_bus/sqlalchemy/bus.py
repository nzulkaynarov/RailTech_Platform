"""`AsyncBus` — rt_bus поверх SQLAlchemy 2 `AsyncSession` (PostgreSQL; драйвер — psycopg 3 или asyncpg).

    bus = AsyncBus(BusConfig(service="crm"), sessions=async_sessionmaker(engine))
    async with sessions() as session, session.begin():
        session.add(client)
        await bus.publish(session, "uz.railtech.crm.client.updated.v1", data, subject="client/42")

Ретранслятор и доставка — `pump()` из периодической задачи (Procrastinate: `rt_bus.contrib.procrastinate`) или
`run_forever()`; после коммита транзакции с `publish` шина будит `pump` сразу (`wakeup=`), не дожидаясь тика;
приёмник — `receive()` (FastAPI: `rt_bus.fastapi.bus_router`), обработка — `process_inbox()`.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import datetime, timedelta
from typing import Any, cast

import httpx
from sqlalchemy import CursorResult, TextClause, event, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from .. import sql
from ..context import correlation
from ..core import (
    RECORD_ATTEMPTS,
    BusConfig,
    BusCore,
    DeliverStats,
    Planned,
    PumpStats,
    Statement,
    as_json,
    finish_statements,
    group_outcomes,
    handler_error,
    inbox_params,
    inbox_retry_at,
    log_outcome,
    plan_groups,
    plan_queued,
    retryable_db_error,
    saturated_subscribers,
)
from ..delivery import Attempt, AttemptResult, Claimed, Outcome, delivery_limits, send_async
from ..envelope import Event
from ..errors import NotInTransactionError
from ..handlers import HandlerRegistry, default_registry
from ..journal import BusMetrics, DeliveryView, InboxView, build_metrics, log_metrics
from ..masking import AsyncSecretStash
from ..receiver import ReceiveResult, Rejection, log_rejection

logger = logging.getLogger("rt_bus")

SessionFactory = Callable[[], AsyncSession]
Enqueue = Callable[[str], Awaitable[Any]]
Wakeup = Callable[[], Awaitable[Any]]

#: Метки в `Session.info`: сессия слушается (слушатели ставятся один раз); шина, которую будить; транзакции (корневая
#: и точки сохранения), в которых был `publish`.
_LISTENING = "rt_bus.listening"
_WAKE = "rt_bus.wakeup"
_MARKS = "rt_bus.wakeup_marks"

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


def _wake_after_commit(session: Session) -> None:
    """`after_commit`: RELEASE SAVEPOINT переносит метку на родителя, коммит корневой транзакции будит ретранслятор
    (из sync-слушателя, без await)."""
    marks: set[Any] | None = session.info.get(_MARKS)
    if not marks:
        return
    nested = session.get_nested_transaction()
    if nested is not None:
        if nested in marks:
            marks.discard(nested)
            marks.add(nested.parent)
        return
    marks.clear()
    bus = session.info.get(_WAKE)
    if bus is not None:
        bus._spawn_wakeup()


def _rolled_back(session: Session, previous: Any) -> None:
    """`after_soft_rollback`: откат точки сохранения уносит её метки — `publish` из неё будить не может."""
    marks: set[Any] | None = session.info.get(_MARKS)
    if marks and previous.nested:
        marks.discard(previous)


def _forget_wake(session: Session, transaction: Any) -> None:
    """`after_transaction_end` корневой транзакции (в том числе откат и закрытие сессии): пробуждения не будет."""
    if transaction.parent is None:
        session.info.pop(_MARKS, None)


class _Flight:
    """Доставки в пути одного прохода (`deliver`) или одного `pump`: по задаче на подписчика, общие счётчики и сбои."""

    def __init__(self, stats: DeliverStats | None = None) -> None:
        self.stats = stats if stats is not None else DeliverStats()
        #: Задача подписчика → (подписчик, сколько доставок в ней).
        self.tasks: dict[asyncio.Task[None], tuple[str, int]] = {}
        #: Записи итогов идут по одной: на каждую группу нужно соединение, а число соединений пула ограничено.
        self.record_lock = asyncio.Lock()
        self.failures: list[Exception] = []

    def reap(self) -> None:
        for task in [t for t in self.tasks if t.done()]:
            del self.tasks[task]

    def in_flight(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for subscriber, size in self.tasks.values():
            counts[subscriber] = counts.get(subscriber, 0) + size
        return counts

    async def wait_any(self, seconds: float) -> None:
        if self.tasks:
            await asyncio.wait(set(self.tasks), timeout=seconds, return_when=asyncio.FIRST_COMPLETED)

    async def finish(self) -> None:
        if self.tasks:
            await asyncio.wait(set(self.tasks))
        self.reap()

    async def cancel(self) -> None:
        """Остановка (отмена задачи воркера): запросы прерываются, аренда истечёт, доставки уйдут другому проходу."""
        tasks = list(self.tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.tasks.clear()

    def raise_failure(self) -> None:
        if self.failures:
            raise self.failures[0]


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
        wakeup: Wakeup | None = None,
    ) -> None:
        self.core = BusCore(config)
        self.sessions = sessions
        self.registry = registry if registry is not None else default_registry
        self._http = http
        self._own_http = http is None
        self.enqueue = enqueue
        self.stash = stash
        #: Будит `pump` после коммита транзакции с `publish` (Procrastinate: `tasks.wakeup`). Сбой — лог, не отказ.
        self.wakeup = wakeup
        self._wake_tasks: set[asyncio.Task[None]] = set()

    @property
    def config(self) -> BusConfig:
        return self.core.config

    def _client(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(
                timeout=self.config.http_timeout, follow_redirects=False, limits=delivery_limits()
            )
        return self._http

    async def aclose(self) -> None:
        await self.drain_wakeups()
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
        record = self.core.outbox_record(event, stash_enabled=self.stash is not None)
        if record.secrets and self.stash is not None:
            await self.stash.put(event.id, record.secrets)
        await _exec(session, sql.INSERT_OUTBOX, record.params(self.core.now()))
        self._arm_wakeup(session)
        logger.info("rt_bus_published", extra={"event_id": event.id, "event_type": event.type})
        return event

    # --- пробуждение ретранслятора после коммита -------------------------------------------------------------------

    def _arm_wakeup(self, session: AsyncSession) -> None:
        """Пометить транзакцию сессии: после её коммита — одно пробуждение на сколько угодно `publish`."""
        if self.wakeup is None:
            return
        sync = session.sync_session
        if _LISTENING not in sync.info:
            sync.info[_LISTENING] = True
            event.listen(sync, "after_commit", _wake_after_commit)
            event.listen(sync, "after_soft_rollback", _rolled_back)
            event.listen(sync, "after_transaction_end", _forget_wake)
        sync.info[_WAKE] = self
        marks: set[Any] = sync.info.setdefault(_MARKS, set())
        marks.add(sync.get_nested_transaction() or sync.get_transaction())

    def _spawn_wakeup(self) -> None:
        """Вызывается из `after_commit` (sync-контекст): пробуждение уходит фоновой задачей, коммит не ждёт брокера."""
        try:
            task = asyncio.get_running_loop().create_task(self._wake())
        except RuntimeError:
            logger.warning("rt_bus_wakeup_skipped_no_loop")
            return
        self._wake_tasks.add(task)
        task.add_done_callback(self._wake_tasks.discard)

    async def _wake(self) -> None:
        try:
            if self.wakeup is not None:
                await self.wakeup()
        except Exception:
            logger.exception("rt_bus_wakeup_failed")  # событие дойдёт периодическим проходом

    async def drain_wakeups(self) -> None:
        """Дождаться постановленных пробуждений (остановка сервиса, тесты)."""
        if self._wake_tasks:
            await asyncio.gather(*self._wake_tasks, return_exceptions=True)

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

    async def _claim(
        self, now: datetime, limit: int, skip: Sequence[str] = ()
    ) -> list[tuple[Claimed, dict[str, Any] | None]]:
        """Взять пачку в аренду. `skip` — подписчики, для которых пачку не набирают (в пути уже предел запросов)."""
        breaker = self.config.breaker
        lease_until = now + timedelta(seconds=self.config.lease_seconds)
        token = uuid.uuid4()
        picked: list[tuple[int, bool, datetime | None]] = []
        out: list[tuple[Claimed, dict[str, Any] | None]] = []
        async with self.sessions() as session, session.begin():
            states = (await _exec(session, sql.PAUSED_STATES)).mappings().all()
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
                due = probe[1]
                picked.append((int(probe[0]), True, due if due is not None and due > now else None))
            excluded = blocked + [r["subscriber"] for r in half_open] + disabled + list(skip)
            if limit > len(picked):
                rows = (
                    await _exec(
                        session, sql.CLAIM_DELIVERIES, {"now": now, "excluded": excluded, "limit": limit - len(picked)}
                    )
                ).all()
                picked.extend((int(r[0]), False, None) for r in rows)
            envelopes: dict[uuid.UUID, dict[str, Any] | None] = {}
            for delivery_id, is_probe, early_until in picked:
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
                    early_until=early_until,
                )
                if claimed.event_id not in envelopes:
                    env = (await _exec(session, sql.SELECT_ENVELOPE, {"id": claimed.event_id})).first()
                    envelopes[claimed.event_id] = None if env is None else as_json(env[0])
                out.append((claimed, envelopes[claimed.event_id]))
        return out

    async def before_deliver(self) -> None:
        """Перед каждым набором пачки (`deliver`, шаг `pump`); сервис переопределяет (например, обновить секреты)."""

    async def _plan(self, claimed: list[tuple[Claimed, dict[str, Any] | None]], now: datetime) -> list[Planned]:
        stash_enabled = self.stash is not None
        planned: list[Planned] = []
        for item, envelope in claimed:
            secret_values = None
            if stash_enabled and self.stash is not None and self.core.needs_stash(item.event_type):
                secret_values = await self.stash.get(str(item.event_id))
            planned.append((item, self.core.plan(item, envelope, secret_values, stash_enabled=stash_enabled, now=now)))
        return planned

    async def _send(self, attempt: Attempt) -> AttemptResult:
        return await send_async(
            self._client(),
            attempt,
            self.config.http_timeout,
            self.core.now(),
            deadline=self.config.attempt_deadline,
        )

    async def _launch(
        self, flight: _Flight, claimed: list[tuple[Claimed, dict[str, Any] | None]], now: datetime
    ) -> None:
        """Взятое — по подписчикам: на каждого своя задача (отправка своих запросов и запись своего итога)."""
        for group in plan_groups(await self._plan(claimed, now)):
            subscriber = group[0][0].subscriber
            task = asyncio.get_running_loop().create_task(self._deliver_group(flight, group))
            flight.tasks[task] = (subscriber, len(group))

    async def _deliver_group(self, flight: _Flight, group: list[Planned]) -> None:
        """Задача подписчика (W11C-G-1): запросы группы идут параллельно, итог пишется, как только ответили ВСЕ запросы
        группы, — не дожидаясь ответов других подписчиков. Сбой записи не поднимается из задачи: он копится в `flight`,
        прочие подписчики продолжают."""
        subscriber = group[0][0].subscriber
        try:
            results = list(await asyncio.gather(*(self._send(p) for _, p in group if isinstance(p, Attempt))))
            finished_at = self.core.now()
            outcomes = group_outcomes(self.config, group, results, finished_at)
            async with flight.record_lock:
                await self._record_group(outcomes, finished_at, flight.stats)
        except Exception as exc:
            logger.exception("rt_bus_record_failed", extra={"subscriber": subscriber})
            flight.failures.append(exc)

    async def deliver(self, limit: int | None = None) -> DeliverStats:
        """Один проход: взять пачку готовых доставок в аренду, отправить, записать итоги. Подписчики независимы
        (W11C-G-1): итог каждого пишется, как только ответил он сам; проход кончается, когда закончили все. HTTP — вне
        транзакций. `pump()` не ждёт медленных между проходами."""
        flight = _Flight()
        await self.before_deliver()
        now = self.core.now()
        claimed = await self._claim(now, limit or self.config.delivery_batch)
        if not claimed:
            return flight.stats
        flight.stats.claimed = len(claimed)
        try:
            await self._launch(flight, claimed, now)
            await flight.finish()
        except BaseException:
            await flight.cancel()
            raise
        flight.raise_failure()
        return flight.stats

    async def _record_group(self, group: list[tuple[Claimed, Outcome]], now: datetime, stats: DeliverStats) -> None:
        for attempt in range(1, RECORD_ATTEMPTS + 1):
            local = DeliverStats()
            try:
                async with self.sessions() as session, session.begin():
                    for item, outcome in group:
                        await self._record(session, item, outcome, now, local)
            except Exception as exc:
                if attempt == RECORD_ATTEMPTS or not retryable_db_error(exc):
                    raise
                logger.warning("rt_bus_record_retry", extra={"subscriber": group[0][0].subscriber, "attempt": attempt})
                await asyncio.sleep(0.05 * attempt * (1.0 + self.config.rng.random()))
                continue
            stats.merge(local)
            return

    async def _record(
        self, session: AsyncSession, item: Claimed, outcome: Outcome, now: datetime, stats: DeliverStats
    ) -> None:
        finish, breaker = finish_statements(self.core, item, outcome, now)
        if _rowcount(await _exec(session, finish.sql, finish.params)) == 0:
            stats.lost_lease += 1
            logger.warning("rt_bus_lease_lost", extra={"delivery_id": item.id, "subscriber": item.subscriber})
            return
        stats.count(outcome)
        failures = await self._breaker(session, breaker, item, now, stats)
        log_outcome(item, outcome, failures, self.config.breaker.threshold)

    async def _breaker(
        self, session: AsyncSession, statement: Statement | None, item: Claimed, now: datetime, stats: DeliverStats
    ) -> int | None:
        if statement is None:
            return None
        result = await _exec(session, statement.sql, statement.params)
        if statement.sql is sql.BREAKER_FAILURE:
            return int(result.first()[0])
        if statement.sql is sql.BREAKER_SUCCESS and int(result.scalar_one()) >= self.config.breaker.threshold:
            # Подписчик восстановился (C1-G-6): накопленные повторы уходят сразу, а не по расписанию.
            reset = await _exec(session, sql.RESET_BACKLOG, {"subscriber": item.subscriber, "now": now})
            stats.recovered += 1
            logger.info("rt_bus_subscriber_recovered", extra={"subscriber": item.subscriber, "reset": _rowcount(reset)})
        return None

    async def _relay_pending(self, deadline: float) -> int:
        relayed = 0
        while time.monotonic() < deadline:
            step = await self.relay()
            relayed += step
            if step < self.config.relay_batch:
                break
        return relayed

    async def pump(self, *, max_seconds: float = 20.0) -> PumpStats:
        """Раскладка outbox и доставка, пока есть работа (не дольше `max_seconds`) — тело периодической задачи.

        Подписчики независимы (W11C-G-1): `pump` не ждёт ответа медленного подписчика, чтобы взять следующую пачку для
        остальных. Пока запросы в пути, он каждые `inflight_poll` секунд раскладывает новое и набирает пачку — кроме
        подписчиков, у которых в пути уже `subscriber_concurrency` запросов. Итог каждого пишется, когда ответил он
        сам. Когда времени или работы нет, `pump` дожидается запросов в пути (дедлайн попытки ограничивает ожидание)."""
        stats = PumpStats()
        deadline = time.monotonic() + max_seconds
        flight = _Flight(stats.deliver)
        failure: Exception | None = None
        stopping = False
        seen_recovered = 0
        try:
            while True:
                claimed_count = 0
                saturated: list[str] = []
                stopping = stopping or time.monotonic() >= deadline
                if not stopping:
                    try:
                        stats.relayed += await self._relay_pending(deadline)
                        await self.before_deliver()
                        now = self.core.now()
                        saturated = saturated_subscribers(flight.in_flight(), self.config.subscriber_concurrency)
                        claimed = await self._claim(now, self.config.delivery_batch, saturated)
                        claimed_count = len(claimed)
                        if claimed:
                            stats.deliver.claimed += claimed_count
                            await self._launch(flight, claimed, now)
                    except Exception as exc:
                        # раскладка или набор упали: уже летящие запросы дописываются (их итоги не теряем), затем ошибка
                        logger.exception("rt_bus_pump_step_failed")
                        failure = failure or exc
                        stopping = True
                flight.reap()
                recovered = stats.deliver.recovered != seen_recovered
                seen_recovered = stats.deliver.recovered
                if not flight.tasks:
                    # короткая пачка = работы нет, если никого не пропускали
                    if stopping or (claimed_count < self.config.delivery_batch and not recovered and not saturated):
                        break
                elif stopping or claimed_count < self.config.delivery_batch:
                    await flight.wait_any(self.config.inflight_poll)
        except BaseException:
            await flight.cancel()
            raise
        if failure is not None:
            raise failure
        flight.raise_failure()
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
                    if row["next_attempt_at"] is not None and row["next_attempt_at"] > self.core.now():
                        return sql.RECEIVED  # ждёт автоповтора — раньше срока не обрабатываем
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
                now = self.core.now()
                async with session.begin():
                    bumped = (
                        await _exec(
                            session, sql.INBOX_FAILURE, {"event_id": key, "error": handler_error(exc), "now": now}
                        )
                    ).first()
                    if bumped is None:
                        return None
                    retry_at = inbox_retry_at(self.core, int(bumped[0]), now)
                    if retry_at is not None:
                        await _exec(session, sql.INBOX_RETRY_LATER, {"event_id": key, "next_attempt_at": retry_at})
                        return sql.RECEIVED
                    await _exec(session, sql.INBOX_FAILED, {"event_id": key})
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
        """Записи `received`, которых не взяла очередь (сбой постановки), и автоповторы, чей срок настал, — снова в
        очередь (без очереди — обработать здесь). Отметка времени не даёт ставить ту же запись на каждом подборе."""
        now = self.core.now()
        before = now - timedelta(seconds=older_than)
        async with self.sessions() as session, session.begin():
            rows = (await _exec(session, sql.STUCK_INBOX, {"before": before, "now": now, "limit": limit})).all()
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
        return build_metrics(
            self.core.now(), outbox, deliveries, states, inbox, disabled=self.core.disabled_subscribers()
        )

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
