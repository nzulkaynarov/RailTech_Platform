"""Корреляция: `correlationid` и `traceparent` в contextvars (runbook §2, L1).

Middleware сервиса ставит контекст из `X-Request-ID` / `traceparent` входящего запроса; `publish` берёт его в конверт
(иначе — новый UUID); обработчик события выполняется в контексте из конверта; фильтр логов и процессор structlog
добавляют `correlation_id` в каждую запись.
"""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import Iterator, Mapping, MutableMapping
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Any

#: Формат `correlationid` конверта (envelope.v1.json): UUID или X-Request-ID без пробелов, до 128 символов.
CORRELATION_ID_RE = re.compile(r"^[A-Za-z0-9._:/+=-]{1,128}$")
#: W3C Trace Context.
TRACEPARENT_RE = re.compile(r"^[0-9a-f]{2}-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}$")

REQUEST_ID_HEADER = "X-Request-ID"
TRACEPARENT_HEADER = "traceparent"

_correlation_id: ContextVar[str | None] = ContextVar("rt_bus_correlation_id", default=None)
_traceparent: ContextVar[str | None] = ContextVar("rt_bus_traceparent", default=None)


@dataclass(frozen=True)
class CorrelationToken:
    """Токены для `reset_correlation` (вернуть контекст, каким он был до `set_correlation`)."""

    correlation_id: Token[str | None]
    traceparent: Token[str | None]


def get_correlation_id() -> str | None:
    return _correlation_id.get()


def get_traceparent() -> str | None:
    return _traceparent.get()


def valid_correlation_id(value: str | None) -> str | None:
    """Значение, пригодное для `correlationid`, или `None`."""
    value = (value or "").strip()
    return value if CORRELATION_ID_RE.match(value) else None


def valid_traceparent(value: str | None) -> str | None:
    value = (value or "").strip().lower()
    return value if TRACEPARENT_RE.match(value) else None


def new_correlation_id() -> str:
    return str(uuid.uuid4())


def set_correlation(correlation_id: str | None, traceparent: str | None = None) -> CorrelationToken:
    """Поставить корреляцию текущего контекста; неверные значения отбрасываются."""
    return CorrelationToken(
        _correlation_id.set(valid_correlation_id(correlation_id)),
        _traceparent.set(valid_traceparent(traceparent)),
    )


def reset_correlation(token: CorrelationToken) -> None:
    _correlation_id.reset(token.correlation_id)
    _traceparent.reset(token.traceparent)


@contextmanager
def correlation(correlation_id: str | None, traceparent: str | None = None) -> Iterator[None]:
    """`with correlation(cid, tp): ...` — контекст на время блока."""
    token = set_correlation(correlation_id, traceparent)
    try:
        yield
    finally:
        reset_correlation(token)


def correlation_from_headers(headers: Mapping[str, str]) -> tuple[str, str | None]:
    """(`correlation_id`, `traceparent`) из заголовков запроса; нет или неверный `X-Request-ID` — новый UUID."""
    lowered = {k.lower(): v for k, v in headers.items()}
    cid = valid_correlation_id(lowered.get(REQUEST_ID_HEADER.lower())) or new_correlation_id()
    return cid, valid_traceparent(lowered.get(TRACEPARENT_HEADER))


class CorrelationFilter(logging.Filter):
    """Фильтр stdlib-логов: `record.correlation_id` и `record.traceparent` (`-`, если контекста нет).

    Подключение: `handler.addFilter(CorrelationFilter())`, в формате — `%(correlation_id)s`.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "correlation_id"):
            record.correlation_id = get_correlation_id() or "-"
        if not hasattr(record, "traceparent"):
            record.traceparent = get_traceparent() or "-"
        return True


def structlog_processor(_logger: Any, _method: str, event_dict: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    """Процессор structlog: добавляет `correlation_id` (и `traceparent`), если их нет в записи."""
    cid = get_correlation_id()
    if cid is not None:
        event_dict.setdefault("correlation_id", cid)
    tp = get_traceparent()
    if tp is not None:
        event_dict.setdefault("traceparent", tp)
    return event_dict
