"""Журнал и метрики шины: строки доставок и inbox для «Журнала интеграций», метрики в лог (runbook §2)."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

from .sql import DEAD, FAILED, IN_FLIGHT, PENDING, RECEIVED

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


@dataclass
class BusMetrics:
    """Метрики издателя (outbox и доставки) и приёмника (inbox)."""

    outbox_pending: int = 0
    oldest_undelivered_age_seconds: float | None = None
    dlq_size: int = 0
    inbox_received: int = 0
    inbox_failed: int = 0
    oldest_inbox_received_age_seconds: float | None = None
    subscribers: dict[str, SubscriberMetrics] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


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
) -> BusMetrics:
    metrics = BusMetrics()
    if outbox is not None:
        metrics.outbox_pending = int(outbox["pending"] or 0)
        metrics.oldest_undelivered_age_seconds = _age(now, outbox["oldest"])
    for row in deliveries:
        sub = metrics.subscribers.setdefault(row["subscriber"], SubscriberMetrics(row["subscriber"]))
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
        metrics.oldest_undelivered_age_seconds = _older(metrics.oldest_undelivered_age_seconds, age)
    for row in states:
        sub = metrics.subscribers.setdefault(row["subscriber"], SubscriberMetrics(row["subscriber"]))
        sub.consecutive_failures = int(row["consecutive_failures"])
        sub.paused = row["paused_until"] is not None and row["paused_until"] > now
    for row in inbox:
        if row["status"] == RECEIVED:
            metrics.inbox_received = int(row["n"])
            metrics.oldest_inbox_received_age_seconds = _age(now, row["oldest"])
        elif row["status"] == FAILED:
            metrics.inbox_failed = int(row["n"])
    return metrics


def log_metrics(service: str, metrics: BusMetrics) -> None:
    """Одна строка лога `rt_bus_metrics` со всеми метриками (поля — в `extra`)."""
    logger.info(
        "rt_bus_metrics service=%s outbox_pending=%d oldest_undelivered_age_s=%s dlq=%d inbox_received=%d "
        "inbox_failed=%d paused=%s",
        service,
        metrics.outbox_pending,
        "-" if metrics.oldest_undelivered_age_seconds is None else int(metrics.oldest_undelivered_age_seconds),
        metrics.dlq_size,
        metrics.inbox_received,
        metrics.inbox_failed,
        ",".join(sorted(s.subscriber for s in metrics.subscribers.values() if s.paused)) or "-",
        extra={"rt_bus_service": service, "rt_bus_metrics": metrics.as_dict()},
    )
