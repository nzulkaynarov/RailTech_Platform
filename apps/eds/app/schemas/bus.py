"""Схемы «Журнала интеграций» шины rt_bus (W13-A2): сводка подписчиков, доставки, inbox, повтор.

Одинаковые поля у CRM, ERP и EDS (BFF сводит три домена в один журнал). Тела событий здесь нет:
только метаданные доставки — тип, id события, издатель, подписчик, статус, попытки, ошибка, время
(`docs/architecture/rt-bus.md`, раздел «Журнал в Admin»).
"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SUBSCRIBER_PATTERN = r"^[a-z][a-z0-9-]{0,63}$"
DeliveryStatus = Literal["pending", "in_flight", "delivered", "dead"]
InboxStatus = Literal["received", "processed", "failed", "skipped"]


class _View(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class BusSubscriber(_View):
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


class BusOverview(_View):
    service: str
    outbox_pending: int
    oldest_undelivered_age_seconds: float | None
    dlq_size: int
    inbox_received: int
    inbox_retrying: int
    inbox_failed: int
    subscribers: list[BusSubscriber]


class BusDelivery(_View):
    id: int
    event_id: uuid.UUID
    event_type: str
    subscriber: str
    status: DeliveryStatus
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


class BusDeliveryPage(BaseModel):
    items: list[BusDelivery]
    has_more: bool


class BusInboxEntry(_View):
    event_id: uuid.UUID
    type: str
    publisher: str
    subject: str | None
    correlation_id: str | None
    status: InboxStatus
    attempts: int
    error: str | None
    received_at: datetime
    processed_at: datetime | None


class BusInboxPage(BaseModel):
    items: list[BusInboxEntry]
    has_more: bool


class BusRetryDeadIn(BaseModel):
    """«Повторить все dead подписчика»."""

    model_config = ConfigDict(extra="forbid")

    subscriber: str = Field(pattern=SUBSCRIBER_PATTERN)


class BusRetryResult(BaseModel):
    """Сколько поставлено на повтор.

    0 — повторять нечего: уже доставлено, уже в работе или записи нет."""

    retried: int
