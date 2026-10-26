"""Модели Admin · Журнал интеграций (контракт: tag `bus`, 0.9.0) и ответов журнала шины доменов.

Домены (CRM `crm.yaml` `BusOverviewOut`…, ERP `erp-internal.yaml` `BusOverview`…, EDS `eds.yaml`
`BusOverview`…) отдают
одни и те же поля — общий код `rt_bus`; BFF читает их терпимо (лишние поля отбрасываются) и
добавляет домен и состояние
подписчика словом. Тел событий нет ни у доменов, ни здесь.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

BusDomain = Literal["crm", "erp", "eds"]
BusSourceState = Literal["ok", "unavailable", "forbidden", "not_applicable"]
DeliveryStatus = Literal["pending", "in_flight", "delivered", "dead"]
InboxStatus = Literal["received", "processed", "failed", "skipped"]
SubscriberState = Literal["ok", "failing", "paused", "dead_letters", "disabled", "removed"]
SUBSCRIBER_PATTERN = r"^[a-z][a-z0-9-]{0,63}$"
DOMAINS: tuple[BusDomain, ...] = ("crm", "erp", "eds")


class _Tolerant(BaseModel):
    """Ответ домена: читатель терпимый — лишние поля не ошибка."""

    model_config = ConfigDict(extra="ignore")


# --- ответы доменов -------------------------------------------------------------------------------


class DomainSubscriber(_Tolerant):
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


class DomainOverview(_Tolerant):
    outbox_pending: int
    oldest_undelivered_age_seconds: float | None
    dlq_size: int
    inbox_received: int
    inbox_retrying: int
    inbox_failed: int
    subscribers: list[DomainSubscriber]


class DomainDelivery(_Tolerant):
    id: int
    event_id: str
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


class DomainDeliveryPage(_Tolerant):
    items: list[DomainDelivery]
    has_more: bool


class DomainInboxEntry(_Tolerant):
    event_id: str
    type: str
    publisher: str
    subject: str | None
    correlation_id: str | None
    status: InboxStatus
    attempts: int
    error: str | None
    received_at: datetime
    processed_at: datetime | None


class DomainInboxPage(_Tolerant):
    items: list[DomainInboxEntry]
    has_more: bool


class DomainRetry(_Tolerant):
    retried: int = Field(ge=0)


# --- ответы BFF -----------------------------------------------------------------------------------


class BusSources(BaseModel):
    crm: BusSourceState
    erp: BusSourceState
    eds: BusSourceState


class BusSubscriber(DomainSubscriber):
    model_config = ConfigDict(extra="forbid")

    state: SubscriberState


class BusDomainOverview(BaseModel):
    domain: BusDomain
    outbox_pending: int
    oldest_undelivered_age_seconds: float | None
    dlq_size: int
    inbox_received: int
    inbox_retrying: int
    inbox_failed: int
    subscribers: list[BusSubscriber]


class BusJournal(BaseModel):
    domains: list[BusDomainOverview]
    sources: BusSources


class BusDelivery(DomainDelivery):
    model_config = ConfigDict(extra="forbid")

    domain: BusDomain


class BusDeliveryPage(BaseModel):
    items: list[BusDelivery]
    next_cursor: str | None
    sources: BusSources


class BusInboxEntry(DomainInboxEntry):
    model_config = ConfigDict(extra="forbid")

    domain: BusDomain


class BusInboxPage(BaseModel):
    items: list[BusInboxEntry]
    next_cursor: str | None
    sources: BusSources


class BusRetryDeadIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subscriber: str = Field(pattern=SUBSCRIBER_PATTERN)


class BusRetryResult(BaseModel):
    retried: int
