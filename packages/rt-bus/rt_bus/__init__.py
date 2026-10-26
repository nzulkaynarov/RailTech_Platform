"""rt_bus — шина событий RailTech Platform v1 (ADR-0014; CONTRACTS §9; docs/architecture/rt-bus.md).

Ядро без фреймворков: конверт CloudEvents, схемы, подписки, подпись, политика повторов, приёмник. Адаптеры:
`rt_bus.sqlalchemy` (async), `rt_bus.django`, `rt_bus.memory` (BFF без БД); обёртки `rt_bus.fastapi`,
`rt_bus.django.views`; задачи очередей `rt_bus.contrib.celery`, `rt_bus.contrib.procrastinate`.
"""

from .context import (
    CorrelationFilter,
    correlation,
    correlation_from_headers,
    get_correlation_id,
    get_traceparent,
    reset_correlation,
    set_correlation,
    structlog_processor,
)
from .core import BusConfig, BusCore, DeliverStats, PumpStats
from .envelope import Event, EventType, new_event, parse_type
from .errors import (
    ConfigError,
    EventValidationError,
    InTransactionError,
    NotInTransactionError,
    RtBusError,
    SubscriptionsError,
    UnknownEventTypeError,
)
from .handlers import Handler, HandlerRegistry, default_registry, subscribe
from .journal import BusMetrics, BusOverview, DeliveryView, InboxView, SubscriberMetrics, SubscriberView
from .masking import DEFAULT_SECRET_FIELDS, MemoryStash
from .policy import BreakerPolicy, RetryPolicy
from .receiver import ReceiveResult
from .schemas import SchemaRegistry
from .signing import env_secrets, secret_env_name, sign, static_secrets, verify
from .subscriptions import Subscriber, Subscriptions, SubscriptionsSource

__all__ = [
    "DEFAULT_SECRET_FIELDS",
    "BreakerPolicy",
    "BusConfig",
    "BusCore",
    "BusMetrics",
    "BusOverview",
    "ConfigError",
    "CorrelationFilter",
    "DeliverStats",
    "DeliveryView",
    "Event",
    "EventType",
    "EventValidationError",
    "Handler",
    "HandlerRegistry",
    "InTransactionError",
    "InboxView",
    "MemoryStash",
    "NotInTransactionError",
    "PumpStats",
    "ReceiveResult",
    "RetryPolicy",
    "RtBusError",
    "SchemaRegistry",
    "Subscriber",
    "SubscriberMetrics",
    "SubscriberView",
    "Subscriptions",
    "SubscriptionsError",
    "SubscriptionsSource",
    "UnknownEventTypeError",
    "correlation",
    "correlation_from_headers",
    "default_registry",
    "env_secrets",
    "get_correlation_id",
    "get_traceparent",
    "new_event",
    "parse_type",
    "reset_correlation",
    "secret_env_name",
    "set_correlation",
    "sign",
    "static_secrets",
    "structlog_processor",
    "subscribe",
    "verify",
]

__version__ = "0.1.0"
