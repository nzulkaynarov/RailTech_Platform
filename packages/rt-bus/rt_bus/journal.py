"""Журнал и метрики шины: строки доставок и inbox для «Журнала интеграций», метрики в лог (runbook §2)."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, field
from datetime import datetime
from fnmatch import fnmatchcase
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from .sql import DEAD, FAILED, IN_FLIGHT, PENDING, RECEIVED
from .subscriptions import Subscriber, Subscriptions

logger = logging.getLogger("rt_bus.metrics")


@dataclass(frozen=True)
class DeliveryView:
    id: int
    event_id: uuid.UUID
    event_type: str
    subscriber: str
    status: str
    attempts: int
    next_attempt_at: datetime | None
    last_attempt_at: datetime | None
    last_status_code: int | None
    last_error: str | None
    delivered_at: datetime | None
    created_at: datetime
    subject: str | None
    correlation_id: str | None
    event_created_at: datetime | None

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> DeliveryView:
        return cls(**{name: row[name] for name in cls.__dataclass_fields__})


@dataclass(frozen=True)
class InboxView:
    event_id: uuid.UUID
    type: str
    source: str
    publisher: str
    subject: str | None
    correlation_id: str | None
    status: str
    attempts: int
    error: str | None
    received_at: datetime
    processed_at: datetime | None

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> InboxView:
        return cls(**{name: row[name] for name in cls.__dataclass_fields__})


@dataclass
class SubscriberMetrics:
    subscriber: str
    pending: int = 0
    in_flight: int = 0
    dead: int = 0
    oldest_undelivered_age_seconds: float | None = None
    consecutive_failures: int = 0
    paused: bool = False
    #: `False` — подписчик выключен (`enabled: false`): его ожидающие доставки копятся намеренно и в общий
    #: `oldest_undelivered_age_seconds` не входят (алерт «старше часа» не авария).
    enabled: bool = True


@dataclass
class BusMetrics:
    """Метрики издателя (outbox и доставки) и приёмника (inbox)."""

    outbox_pending: int = 0
    oldest_undelivered_age_seconds: float | None = None
    dlq_size: int = 0
    inbox_received: int = 0
    #: Из них ждут автоповтора обработки (BusConfig.inbox_retry_delays).
    inbox_retrying: int = 0
    inbox_failed: int = 0
    oldest_inbox_received_age_seconds: float | None = None
    subscribers: dict[str, SubscriberMetrics] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SubscriberView:
    """Подписчик издателя для «Журнала интеграций» (W13-A2): настройка, очередь доставок, предохранитель.

    `configured = False` — подписчика больше нет в файле подписок, но у него остались доставки или состояние.
    `paused_until` — только действующая пауза предохранителя (в будущем); прошедшая — `None`.
    """

    name: str
    configured: bool
    enabled: bool
    drop: bool
    endpoint: str | None
    pending: int
    in_flight: int
    dead: int
    oldest_undelivered_age_seconds: float | None
    consecutive_failures: int
    paused_until: datetime | None
    last_failure_at: datetime | None
    last_success_at: datetime | None
    last_error: str | None


@dataclass(frozen=True)
class BusOverview:
    """Сводка издателя и приёмника сервиса для «Журнала интеграций»: метрики и подписчики."""

    service: str
    outbox_pending: int
    oldest_undelivered_age_seconds: float | None
    dlq_size: int
    inbox_received: int
    inbox_retrying: int
    inbox_failed: int
    subscribers: list[SubscriberView]


def public_endpoint(url: str) -> str:
    """Адрес приёмника без учётных данных в URL (`user:pass@` не показываем даже администратору)."""
    parts = urlsplit(url)
    if parts.username is None and parts.password is None:
        return url
    host = parts.hostname or ""
    if parts.port is not None:
        host = f"{host}:{parts.port}"
    return urlunsplit((parts.scheme, host, parts.path, parts.query, parts.fragment))


def serves(subscriber: Subscriber, service: str, domains: Iterable[str]) -> bool:
    """Получает ли подписчик события издателя `service`: не он сам и хотя бы одна маска — на домен издателя
    (`uz.railtech.<домен>.…`; маска домена с подстановкой сравнивается как fnmatch)."""
    if subscriber.name == service:
        return False
    owned = tuple(domains)
    for mask in subscriber.types:
        parts = mask.split(".")
        domain = parts[2] if len(parts) > 3 else ""
        if any(fnmatchcase(own, domain) for own in owned):
            return True
    return False


def build_subscribers(
    now: datetime,
    service: str,
    domains: Iterable[str],
    subscriptions: Subscriptions,
    deliveries: Iterable[Mapping[str, Any]],
    states: Iterable[Mapping[str, Any]],
    environ: Mapping[str, str] | None = None,
) -> list[SubscriberView]:
    """Подписчики издателя по имени: из файла подписок (только те, кому издатель доставляет) и все, у кого есть
    доставки `pending`/`in_flight`/`dead` или состояние предохранителя. Строки `deliveries` — `METRICS_DELIVERY`,
    `states` — `SUBSCRIBER_STATES`."""
    owned = tuple(domains)
    counts: dict[str, dict[str, int]] = {}
    oldest: dict[str, float | None] = {}
    for row in deliveries:
        name = row["subscriber"]
        counts.setdefault(name, {})[row["status"]] = int(row["n"])
        if row["status"] != DEAD:
            oldest[name] = _older(oldest.get(name), _age(now, row["oldest"]))
    state_by_name = {row["subscriber"]: row for row in states}
    configured = {s.name: s for s in subscriptions.subscribers if serves(s, service, owned)}
    names = sorted(set(configured) | set(counts) | set(state_by_name))
    out: list[SubscriberView] = []
    for name in names:
        sub = configured.get(name) or subscriptions.get(name)
        state = state_by_name.get(name) or {}
        paused_until = state.get("paused_until")
        by_status = counts.get(name, {})
        out.append(
            SubscriberView(
                name=name,
                configured=name in configured,
                enabled=sub.enabled if sub is not None else True,
                drop=sub.drop if sub is not None else False,
                endpoint=public_endpoint(sub.url(environ)) if sub is not None else None,
                pending=by_status.get(PENDING, 0),
                in_flight=by_status.get(IN_FLIGHT, 0),
                dead=by_status.get(DEAD, 0),
                oldest_undelivered_age_seconds=oldest.get(name),
                consecutive_failures=int(state.get("consecutive_failures") or 0),
                paused_until=paused_until if paused_until is not None and paused_until > now else None,
                last_failure_at=state.get("last_failure_at"),
                last_success_at=state.get("last_success_at"),
                last_error=state.get("last_error"),
            )
        )
    return out


def build_overview(service: str, metrics: BusMetrics, subscribers: list[SubscriberView]) -> BusOverview:
    return BusOverview(
        service=service,
        outbox_pending=metrics.outbox_pending,
        oldest_undelivered_age_seconds=metrics.oldest_undelivered_age_seconds,
        dlq_size=metrics.dlq_size,
        inbox_received=metrics.inbox_received,
        inbox_retrying=metrics.inbox_retrying,
        inbox_failed=metrics.inbox_failed,
        subscribers=subscribers,
    )


def delivery_filters(
    *,
    status: str | None,
    subscriber: str | None,
    event_type: str | None,
    event_id: str | uuid.UUID | None,
    type_contains: str | None,
    created_from: datetime | None,
    created_to: datetime | None,
    before_id: int | None,
    limit: int,
) -> dict[str, Any]:
    """Параметры `LIST_DELIVERIES` (одни для обоих адаптеров)."""
    return {
        "status": status,
        "subscriber": subscriber,
        "event_type": event_type,
        "event_id": None if event_id is None else uuid.UUID(str(event_id)),
        "type_contains": type_contains or None,
        "created_from": created_from,
        "created_to": created_to,
        "before_id": before_id,
        "limit": limit,
    }


def inbox_filters(
    *,
    status: str | None,
    event_type: str | None,
    type_contains: str | None,
    errors_only: bool,
    before: datetime | None,
    before_event_id: str | uuid.UUID | None,
    limit: int,
) -> dict[str, Any]:
    """Параметры `LIST_INBOX`. Курсор — (`before`, `before_event_id`) последней строки страницы: порядок
    `received_at DESC, event_id`, поэтому строки с тем же временем не теряются между страницами."""
    return {
        "status": status,
        "event_type": event_type,
        "type_contains": type_contains or None,
        "errors_only": errors_only,
        "before": before,
        "before_event_id": None if before_event_id is None else uuid.UUID(str(before_event_id)),
        "limit": limit,
    }


def _age(now: datetime, moment: datetime | None) -> float | None:
    return None if moment is None else max((now - moment).total_seconds(), 0.0)


def _older(a: float | None, b: float | None) -> float | None:
    values = [x for x in (a, b) if x is not None]
    return max(values) if values else None


def build_metrics(
    now: datetime,
    outbox: Mapping[str, Any] | None,
    deliveries: Iterable[Mapping[str, Any]],
    states: Iterable[Mapping[str, Any]],
    inbox: Iterable[Mapping[str, Any]],
    disabled: Iterable[str] = (),
) -> BusMetrics:
    off = frozenset(disabled)
    metrics = BusMetrics()
    if outbox is not None:
        metrics.outbox_pending = int(outbox["pending"] or 0)
        metrics.oldest_undelivered_age_seconds = _age(now, outbox["oldest"])
    for row in deliveries:
        sub = metrics.subscribers.setdefault(row["subscriber"], SubscriberMetrics(row["subscriber"]))
        sub.enabled = row["subscriber"] not in off
        count = int(row["n"])
        if row["status"] == DEAD:
            sub.dead += count
            metrics.dlq_size += count
            continue
        if row["status"] == PENDING:
            sub.pending += count
        elif row["status"] == IN_FLIGHT:
            sub.in_flight += count
        age = _age(now, row["oldest"])
        sub.oldest_undelivered_age_seconds = _older(sub.oldest_undelivered_age_seconds, age)
        if sub.enabled:
            metrics.oldest_undelivered_age_seconds = _older(metrics.oldest_undelivered_age_seconds, age)
    for row in states:
        sub = metrics.subscribers.setdefault(row["subscriber"], SubscriberMetrics(row["subscriber"]))
        sub.enabled = row["subscriber"] not in off
        sub.consecutive_failures = int(row["consecutive_failures"])
        sub.paused = row["paused_until"] is not None and row["paused_until"] > now
    for row in inbox:
        if row["status"] == RECEIVED:
            metrics.inbox_received = int(row["n"])
            metrics.inbox_retrying = int(row["retrying"] or 0)
            metrics.oldest_inbox_received_age_seconds = _age(now, row["oldest"])
        elif row["status"] == FAILED:
            metrics.inbox_failed = int(row["n"])
    return metrics


def log_metrics(service: str, metrics: BusMetrics) -> None:
    """Одна строка лога `rt_bus_metrics` со всеми метриками (поля — в `extra`)."""
    logger.info(
        "rt_bus_metrics service=%s outbox_pending=%d oldest_undelivered_age_s=%s dlq=%d inbox_received=%d "
        "inbox_retrying=%d inbox_failed=%d paused=%s disabled=%s",
        service,
        metrics.outbox_pending,
        "-" if metrics.oldest_undelivered_age_seconds is None else int(metrics.oldest_undelivered_age_seconds),
        metrics.dlq_size,
        metrics.inbox_received,
        metrics.inbox_retrying,
        metrics.inbox_failed,
        ",".join(sorted(s.subscriber for s in metrics.subscribers.values() if s.paused)) or "-",
        ",".join(sorted(s.subscriber for s in metrics.subscribers.values() if not s.enabled)) or "-",
        extra={"rt_bus_service": service, "rt_bus_metrics": metrics.as_dict()},
    )
