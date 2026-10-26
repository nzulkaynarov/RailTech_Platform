"""Настройки и общая логика шины — одна для адаптеров SQLAlchemy (async) и Django (sync)."""

from __future__ import annotations

import json
import logging
import os
import random
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from . import sql
from .delivery import (
    Attempt,
    AttemptResult,
    BreakerEffect,
    Claimed,
    Outcome,
    OutcomeKind,
    build_attempt,
    clip,
    dead,
    decide_outcome,
    early_probe_outcome,
    pause_until,
    postpone,
)
from .envelope import DEFAULT_TENANT, SERVICE_NAME_RE, Event, new_event, source_for
from .errors import ConfigError, EventValidationError, UnknownEventTypeError
from .handlers import Handler, HandlerRegistry
from .masking import DEFAULT_SECRET_FIELDS, mask_data, redact, unmask_data
from .policy import BreakerPolicy, RetryPolicy
from .receiver import DEFAULT_PUBLISHER_DOMAINS, Accepted, Rejection, decide
from .schemas import SchemaRegistry
from .signing import SecretProvider, env_secrets, secret_env_name
from .subscriptions import Subscriber, Subscriptions, SubscriptionsSource, resolve_subscriptions_path

logger = logging.getLogger("rt_bus")

#: SQLSTATE взаимной блокировки и сбоя сериализации: транзакция откатилась целиком, её можно повторить.
RETRYABLE_SQLSTATES = frozenset({"40P01", "40001"})
#: Сколько раз повторять запись итогов подписчика после взаимной блокировки (с короткой паузой).
RECORD_ATTEMPTS = 4


def utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass
class BusConfig:
    """Настройки шины сервиса.

    `service` — имя сервиса (`crm`, `erp`, `platform-bff`): `source` = `rt://<service>`, имя издателя в `X-RT-Publisher`
    и подписчика в секретах. Каталог схем — `contracts_dir` или `RT_BUS_CONTRACTS_DIR`; файл подписок —
    `subscriptions_path` или `RT_BUS_SUBSCRIPTIONS` (иначе `bus/subscriptions.yaml` рядом с каталогом схем).
    """

    service: str
    contracts_dir: str | os.PathLike[str] | None = None
    subscriptions_path: str | os.PathLike[str] | None = None
    secrets: SecretProvider = env_secrets
    tenant: str = DEFAULT_TENANT
    retry: RetryPolicy = field(default_factory=RetryPolicy)
    breaker: BreakerPolicy = field(default_factory=BreakerPolicy)
    #: Таймаут HTTP одной попытки (httpx, на операцию).
    http_timeout: float = 10.0
    #: Сколько доставок воркер берёт за раз и отправляет параллельно.
    delivery_batch: int = 10
    #: Сколько запросов одному подписчику `pump` держит в пути одновременно (мягкий предел: пачка может добавить до
    #: `delivery_batch - 1`). Подписчик, у которого столько уже в пути, пропускает набор очередной пачки — медленный
    #: подписчик не занимает пачки быстрых (W11C-G-1).
    subscriber_concurrency: int = 20
    #: Как часто `pump`, пока ждёт ответов, заглядывает в базу за новой работой.
    inflight_poll: float = 0.25
    #: Сколько строк outbox раскладывается за раз.
    relay_batch: int = 100
    #: Общий дедлайн одной попытки (запросы идут параллельно, итог пишется по подписчику): медленный ответ не держит
    #: аренду.
    attempt_deadline: float = 25.0
    #: Аренда взятой доставки: дольше дедлайна попытки; упавший воркер отдаёт доставку другому по истечении.
    lease_seconds: float = 60.0
    #: Окно метки подписи у приёмника.
    window_seconds: float = 300.0
    #: Автоповтор обработки записи inbox после ошибки обработчика (± jitter `retry`); затем `failed`.
    inbox_retry_delays: tuple[float, ...] = (30.0, 120.0, 600.0)
    #: Отложить доставку, если попытка невозможна по нашей причине (нет секрета, подписчика нет в файле).
    postpone_seconds: float = 300.0
    secret_fields: Mapping[str, tuple[str, ...]] = field(default_factory=lambda: dict(DEFAULT_SECRET_FIELDS))
    #: Подпись пары у приёмника: домены типов, которые вправе публиковать издатель (по умолчанию —
    #: `DEFAULT_PUBLISHER_DOMAINS`; издателя нет в таблице — только домен с его именем).
    publisher_domains: Mapping[str, frozenset[str]] = field(default_factory=lambda: dict(DEFAULT_PUBLISHER_DOMAINS))
    clock: Callable[[], datetime] = utcnow
    rng: random.Random = field(default_factory=random.Random)

    def __post_init__(self) -> None:
        if not SERVICE_NAME_RE.match(self.service):
            raise ConfigError(f"service name {self.service!r} must match {SERVICE_NAME_RE.pattern}")
        if self.delivery_batch < 1 or self.relay_batch < 1 or self.subscriber_concurrency < 1:
            raise ConfigError("delivery_batch, relay_batch and subscriber_concurrency must be positive")
        if self.inflight_poll <= 0:
            raise ConfigError("inflight_poll must be positive")
        if not self.http_timeout <= self.attempt_deadline <= self.lease_seconds - 10:
            raise ConfigError("need http_timeout <= attempt_deadline <= lease_seconds - 10")


@dataclass(frozen=True)
class OutboxRecord:
    event: Event
    #: Конверт для outbox (секретные поля замаскированы).
    stored_envelope: dict[str, Any]
    secrets: dict[str, Any]

    def params(self, now: datetime) -> dict[str, Any]:
        return {
            "id": uuid.UUID(self.event.id),
            "type": self.event.type,
            "source": self.event.source,
            "subject": self.event.subject,
            "correlation_id": self.event.correlationid,
            "envelope": json.dumps(self.stored_envelope, ensure_ascii=False),
            "now": now,
        }


class BusCore:
    """Схемы, подписки, построение событий, план попытки доставки, решение приёмника."""

    def __init__(self, config: BusConfig) -> None:
        self.config = config
        self._schemas: SchemaRegistry | None = None
        self._subscriptions: SubscriptionsSource | None = None

    @property
    def service(self) -> str:
        return self.config.service

    def now(self) -> datetime:
        return self.config.clock()

    @property
    def schemas(self) -> SchemaRegistry:
        if self._schemas is None:
            self._schemas = SchemaRegistry(self.config.contracts_dir)
        return self._schemas

    @property
    def subscriptions_source(self) -> SubscriptionsSource:
        if self._subscriptions is None:
            path = resolve_subscriptions_path(self.config.subscriptions_path, self.schemas.events_dir)
            self._subscriptions = SubscriptionsSource(path)
        return self._subscriptions

    def subscriptions(self) -> Subscriptions:
        return self.subscriptions_source.current()

    # --- издатель -----------------------------------------------------------------------------------------------

    def build_event(
        self,
        event_type: str,
        data: Mapping[str, Any],
        *,
        subject: str | None = None,
        event_id: str | uuid.UUID | None = None,
        time: datetime | None = None,
        tenant: str | None = None,
        correlationid: str | None = None,
        traceparent: str | None = None,
    ) -> Event:
        """Событие этого сервиса, проверенное строго: конверт и `data` по схеме, иначе `EventValidationError`."""
        try:
            event = new_event(
                type=event_type,
                data=data,
                source=source_for(self.service),
                subject=subject,
                tenant=tenant or self.config.tenant,
                event_id=event_id,
                time=time or self.now(),
                correlationid=correlationid,
                traceparent=traceparent,
            )
        except (TypeError, ValueError) as exc:
            raise EventValidationError(f"cannot build {event_type}: {exc}") from exc
        self.validate_outgoing(event)
        return event

    def validate_outgoing(self, event: Event) -> None:
        if event.source != source_for(self.service):
            raise EventValidationError(f"event source {event.source!r} is not rt://{self.service}")
        errors = self.schemas.validate_envelope(event.to_dict())
        if errors:
            raise EventValidationError(f"envelope of {event.type} is invalid", errors)
        if not self.schemas.has_type(event.type):
            raise UnknownEventTypeError(f"no schema for {event.type} in {self.schemas.events_dir}")
        errors = self.schemas.validate_data(event.type, event.data, tolerant=False)
        if errors:
            paths = self.config.secret_fields.get(event.type, ())
            secrets = mask_data(event.data, paths)[1] if paths else {}
            raise EventValidationError(f"data of {event.type} is invalid", redact(errors, secrets))

    def outbox_record(self, event: Event, *, stash_enabled: bool) -> OutboxRecord:
        """Строка outbox: секретные поля типа (`secret_fields`) заменены маской, значения — отдельно, в хранилище.

        Секрет по умолчанию закрыт: тип с секретными полями без хранилища (`stash=`) — `ConfigError`, а не код
        акцепта открытым текстом в outbox (CONTRACTS §9.2).
        """
        paths = self.config.secret_fields.get(event.type, ())
        if paths and not stash_enabled:
            raise ConfigError(
                f"{event.type} has secret fields {list(paths)}: pass stash= to the bus (e.g. DjangoCacheStash)"
            )
        if not paths:
            return OutboxRecord(event, event.to_dict(), {})
        masked, secrets = mask_data(event.data, paths)
        return OutboxRecord(event, event.with_data(masked).to_dict(), secrets)

    def disabled_subscribers(self) -> list[str]:
        """Выключенные подписчики (`enabled: false`), по имени: их доставки ждут и не берутся в аренду."""
        return sorted(s.name for s in self.subscriptions().subscribers if not s.enabled)

    def targets(self, event_type: str, source: str) -> list[Subscriber]:
        return self.subscriptions().targets(event_type, source, self.service)

    # --- доставка -----------------------------------------------------------------------------------------------

    def needs_stash(self, event_type: str) -> bool:
        return bool(self.config.secret_fields.get(event_type))

    def plan(
        self,
        claimed: Claimed,
        envelope: Mapping[str, Any] | None,
        secret_values: Mapping[str, Any] | None,
        *,
        stash_enabled: bool,
        now: datetime,
    ) -> Attempt | Outcome:
        """Запрос попытки или итог без запроса (нет подписчика или секрета — отложить; нет события — `dead`)."""
        if envelope is None:
            return dead("event not found in rt_bus_outbox")
        subscriber = self.subscriptions().get(claimed.subscriber)
        if subscriber is None:
            return postpone(
                now, self.config.postpone_seconds, f"subscriber {claimed.subscriber!r} not in subscriptions"
            )
        if not subscriber.enabled:
            return postpone(now, self.config.postpone_seconds, f"subscriber {claimed.subscriber!r} is disabled")
        secrets = [s for s in self.config.secrets(self.service, claimed.subscriber) if s]
        if not secrets:
            return postpone(
                now, self.config.postpone_seconds, f"no secret {secret_env_name(self.service, claimed.subscriber)}"
            )
        body = dict(envelope)
        if stash_enabled and self.needs_stash(claimed.event_type):
            if secret_values is None:
                return dead("SECRET_EXPIRED: secret fields of the event are no longer available")
            body["data"] = unmask_data(body.get("data") or {}, secret_values)
        return build_attempt(body, publisher=self.service, url=subscriber.url(), secret=secrets[0], now=now)

    # --- приёмник -----------------------------------------------------------------------------------------------

    def decide(self, registry: HandlerRegistry, headers: Mapping[str, str], body: bytes) -> Accepted | Rejection:
        return decide(
            service=self.service,
            headers=headers,
            body=body,
            schemas=self.schemas,
            registry=registry,
            secrets=self.config.secrets,
            now=self.now(),
            window_seconds=self.config.window_seconds,
            secret_fields=self.config.secret_fields,
            publisher_domains=self.config.publisher_domains,
        )


@dataclass(frozen=True)
class Statement:
    sql: str
    params: dict[str, Any]


def finish_statements(
    core: BusCore, claimed: Claimed, outcome: Outcome, now: datetime
) -> tuple[Statement, Statement | None]:
    """SQL итога попытки: обновление доставки (условно по токену аренды) и, если нужно, предохранителя."""
    base: dict[str, Any] = {"id": claimed.id, "token": claimed.lease_token, "now": now}
    match outcome.kind:
        case OutcomeKind.DELIVERED:
            finish = Statement(sql.FINISH_DELIVERED, {**base, "status_code": outcome.status_code})
        case OutcomeKind.RETRY:
            finish = Statement(
                sql.FINISH_RETRY,
                {
                    **base,
                    "next_attempt_at": outcome.next_attempt_at,
                    "status_code": outcome.status_code,
                    "error": outcome.error,
                },
            )
        case OutcomeKind.POSTPONE:
            finish = Statement(
                sql.FINISH_POSTPONE, {**base, "next_attempt_at": outcome.next_attempt_at, "error": outcome.error}
            )
        case OutcomeKind.DEAD:
            finish = Statement(sql.FINISH_DEAD, {**base, "status_code": outcome.status_code, "error": outcome.error})
    breaker: Statement | None = None
    if outcome.breaker is BreakerEffect.SUCCESS:
        breaker = Statement(sql.BREAKER_SUCCESS, {"subscriber": claimed.subscriber, "now": now})
    elif outcome.breaker is BreakerEffect.FAILURE:
        breaker = Statement(
            sql.BREAKER_FAILURE,
            {
                "subscriber": claimed.subscriber,
                "now": now,
                "threshold": core.config.breaker.threshold,
                "pause_until": pause_until(now, core.config.breaker),
                "error": outcome.error,
            },
        )
    return finish, breaker


def retryable_db_error(exc: BaseException) -> bool:
    """Транзакцию откатила взаимная блокировка или сбой сериализации (SQLSTATE 40P01/40001) — запись можно повторить.

    SQLSTATE ищется по цепочке `orig`/`__cause__`: SQLAlchemy и Django оборачивают ошибку драйвера
    (psycopg 3 и asyncpg — `sqlstate`, psycopg2 — `pgcode`)."""
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        code = getattr(current, "sqlstate", None) or getattr(current, "pgcode", None)
        if code in RETRYABLE_SQLSTATES:
            return True
        nested = getattr(current, "orig", None)
        current = nested if isinstance(nested, BaseException) else current.__cause__
    return False


Planned = tuple[Claimed, Attempt | Outcome]


def plan_groups(planned: list[Planned]) -> list[list[Planned]]:
    """Взятые доставки по подписчикам (W11C-G-1): группа — единица отправки и записи итога. Группы в порядке имён,
    внутри — по `id` доставки.

    Группа отправляется и записывается независимо от остальных: медленный подписчик задерживает только себя. Запись
    группы — одна короткая транзакция, затрагивающая только строки её подписчика (доставки и `rt_bus_subscriber_state`),
    поэтому группы разных подписчиков не могут взаимно заблокироваться (W11B-G-1), а сбой одной не держит аренду
    чужих."""
    groups: dict[str, list[Planned]] = {}
    for pair in sorted(planned, key=lambda p: (p[0].subscriber, p[0].id)):
        groups.setdefault(pair[0].subscriber, []).append(pair)
    return list(groups.values())


def group_outcomes(
    config: BusConfig, group: list[Planned], results: list[AttemptResult], finished_at: datetime
) -> list[tuple[Claimed, Outcome]]:
    """Итоги группы: результаты отправки (по порядку попыток группы) → решения по L3; прочие — как запланировано."""
    attempts = iter(results)
    outcomes: list[tuple[Claimed, Outcome]] = []
    for item, plan in group:
        if isinstance(plan, Attempt):
            outcome = early_probe_outcome(
                item, decide_outcome(item, next(attempts), policy=config.retry, now=finished_at, rng=config.rng)
            )
        else:
            outcome = plan
        outcomes.append((item, outcome))
    return outcomes


def saturated_subscribers(in_flight: Mapping[str, int], limit: int) -> list[str]:
    """Подписчики, у которых в пути уже `limit` запросов и более: очередную пачку для них не набирают."""
    return sorted(name for name, count in in_flight.items() if count >= limit)


def log_outcome(claimed: Claimed, outcome: Outcome, failures: int | None, threshold: int) -> None:
    extra = {
        "delivery_id": claimed.id,
        "event_id": str(claimed.event_id),
        "event_type": claimed.event_type,
        "subscriber": claimed.subscriber,
        "attempt": claimed.attempts,
        "probe": claimed.probe,
        "status_code": outcome.status_code,
        "outcome": outcome.kind.value,
    }
    if outcome.kind is OutcomeKind.DELIVERED:
        logger.info("rt_bus_delivered", extra=extra)
    elif outcome.kind is OutcomeKind.DEAD:
        logger.error("rt_bus_delivery_dead", extra={**extra, "error": outcome.error})
    else:
        logger.warning(
            "rt_bus_delivery_retry",
            extra={**extra, "error": outcome.error, "next_attempt_at": str(outcome.next_attempt_at)},
        )
    if failures is not None and failures >= threshold:
        logger.error(
            "rt_bus_breaker_open",
            extra={"subscriber": claimed.subscriber, "consecutive_failures": failures},
        )


COUNTERS = ("claimed", "delivered", "retried", "dead", "postponed", "lost_lease", "recovered")


@dataclass
class DeliverStats:
    claimed: int = 0
    delivered: int = 0
    retried: int = 0
    dead: int = 0
    postponed: int = 0
    lost_lease: int = 0
    #: Подписчиков, восстановившихся за проход (предохранитель закрыт после порога): их ожидающие доставки сброшены на
    #: «сейчас», `pump` берёт следующую пачку сразу.
    recovered: int = 0

    def merge(self, other: DeliverStats) -> None:
        for name in COUNTERS:
            setattr(self, name, getattr(self, name) + getattr(other, name))

    def count(self, outcome: Outcome) -> None:
        match outcome.kind:
            case OutcomeKind.DELIVERED:
                self.delivered += 1
            case OutcomeKind.RETRY:
                self.retried += 1
            case OutcomeKind.DEAD:
                self.dead += 1
            case OutcomeKind.POSTPONE:
                self.postponed += 1


@dataclass
class PumpStats:
    relayed: int = 0
    deliver: DeliverStats = field(default_factory=DeliverStats)


def as_json(value: Any) -> dict[str, Any]:
    """jsonb из драйвера: psycopg отдаёт dict, Django-курсор — строку."""
    if isinstance(value, str | bytes | bytearray):
        loaded = json.loads(value)
        return loaded if isinstance(loaded, dict) else {}
    return dict(value) if isinstance(value, Mapping) else {}


def inbox_params(accepted: Accepted, now: datetime) -> dict[str, Any]:
    event = accepted.event
    return {
        "event_id": uuid.UUID(event.id),
        "type": event.type,
        "source": event.source,
        "publisher": accepted.publisher,
        "subject": event.subject,
        "correlation_id": event.correlationid,
        "envelope": json.dumps(accepted.stored_envelope, ensure_ascii=False),
        "status": accepted.status,
        "error": accepted.reason,
        "processed_at": now if accepted.status == sql.SKIPPED else None,
        "now": now,
    }


@dataclass(frozen=True)
class QueuedPlan:
    """Что делать с записью inbox в задаче очереди: обработчики или сразу итог (`skipped`/`failed`)."""

    handlers: list[Handler]
    status: str | None = None
    error: str | None = None


def plan_queued(core: BusCore, registry: HandlerRegistry, event: Event) -> QueuedPlan:
    handlers = [h for h in registry.match(event.type) if not h.inline]
    if not handlers:
        inline = any(h.inline for h in registry.match(event.type))
        if inline:
            return QueuedPlan([], sql.PROCESSED, None)
        return QueuedPlan([], sql.SKIPPED, f"no handler for {event.type}")
    if not core.schemas.has_type(event.type):
        return QueuedPlan([], sql.SKIPPED, f"unknown type {event.type}: no schema")
    errors = core.schemas.validate_data(event.type, event.data, tolerant=True)
    if errors:
        return QueuedPlan([], sql.FAILED, "invalid data: " + "; ".join(errors[:5]))
    return QueuedPlan(handlers)


def inbox_retry_at(core: BusCore, attempts: int, now: datetime) -> datetime | None:
    """Когда повторить обработку после неудачной попытки № `attempts`; `None` — повторы кончились (`failed`)."""
    policy = RetryPolicy(delays=core.config.inbox_retry_delays, jitter=core.config.retry.jitter)
    delay = policy.delay_after(attempts, core.config.rng)
    return None if delay is None else now + timedelta(seconds=delay)


def handler_error(exc: BaseException) -> str:
    return clip(f"{type(exc).__name__}: {exc}", 2000)
