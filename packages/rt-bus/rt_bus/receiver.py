"""Приёмник `POST /bus/v1/events` без фреймворка: подпись и окно → разбор конверта → решение (L3, L10).

Хранение в inbox и вызов обработчиков делают адаптеры (SQLAlchemy, Django, память); тонкие обёртки — `rt_bus.fastapi`
и `rt_bus.django.views`.

Ответы: 200 — принято (новое, повтор `id`, `skipped`); 401 — нет или неверная подпись, неизвестный издатель, вне окна,
`source` не совпадает с издателем; 400 — не JSON, не конверт, `id` не совпадает с заголовком; 422 — `data` известного
типа не по схеме (терпимо: `additionalProperties` не отказ); 503 — inline-обработчик упал (издатель повторит).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from .envelope import SERVICE_NAME_RE, Event, source_for
from .errors import UnknownEventTypeError
from .handlers import Handler, HandlerRegistry
from .masking import mask_data
from .schemas import SchemaRegistry
from .signing import (
    HEADER_EVENT_ID,
    HEADER_PUBLISHER,
    HEADER_SIGNATURE,
    HEADER_TIMESTAMP,
    SecretProvider,
    secret_env_name,
    verify,
    window_problem,
)

logger = logging.getLogger("rt_bus.receiver")


@dataclass(frozen=True)
class ReceiveResult:
    """Ответ приёмника: код и JSON-тело."""

    status_code: int
    body: dict[str, Any]


@dataclass(frozen=True)
class Rejection:
    status_code: int
    error: str
    detail: str

    def result(self) -> ReceiveResult:
        return ReceiveResult(self.status_code, {"error": self.error})


@dataclass(frozen=True)
class Accepted:
    """Событие принято к записи в inbox."""

    event: Event
    publisher: str
    stored_envelope: dict[str, Any]
    status: Literal["received", "skipped"]
    reason: str | None = None
    inline: list[Handler] = field(default_factory=list)
    queued: list[Handler] = field(default_factory=list)


def lower_headers(headers: Mapping[str, str]) -> dict[str, str]:
    return {str(k).lower(): str(v) for k, v in headers.items()}


def decide(
    *,
    service: str,
    headers: Mapping[str, str],
    body: bytes,
    schemas: SchemaRegistry,
    registry: HandlerRegistry,
    secrets: SecretProvider,
    now: datetime,
    window_seconds: float,
    secret_fields: Mapping[str, tuple[str, ...]],
) -> Accepted | Rejection:
    h = lower_headers(headers)
    publisher = h.get(HEADER_PUBLISHER.lower(), "").strip()
    if not SERVICE_NAME_RE.match(publisher):
        return Rejection(401, "unauthorized", "missing or invalid X-RT-Publisher")
    pair_secrets = [s for s in secrets(publisher, service) if s]
    if not pair_secrets:
        return Rejection(
            401, "unauthorized", f"unknown publisher {publisher!r}: no secret {secret_env_name(publisher, service)}"
        )
    event_id = h.get(HEADER_EVENT_ID.lower(), "").strip()
    timestamp = h.get(HEADER_TIMESTAMP.lower(), "").strip()
    signature = h.get(HEADER_SIGNATURE.lower(), "").strip()
    if not (event_id and timestamp and signature):
        return Rejection(401, "unauthorized", "missing X-RT-Event-Id, X-RT-Timestamp or X-RT-Signature")
    if not verify(pair_secrets, event_id, timestamp, body, signature):
        return Rejection(401, "unauthorized", f"invalid signature from {publisher!r}")
    problem = window_problem(timestamp, now, window_seconds)
    if problem is not None:
        return Rejection(401, "unauthorized", problem)

    try:
        payload = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return Rejection(400, "invalid_json", "body is not JSON")
    errors = schemas.validate_envelope(payload)
    if errors:
        return Rejection(400, "invalid_envelope", "; ".join(errors[:5]))
    if str(payload["id"]) != event_id:
        return Rejection(400, "invalid_envelope", "envelope id does not match X-RT-Event-Id")
    if payload["source"] != source_for(publisher):
        return Rejection(401, "unauthorized", f"source {payload['source']!r} is not publisher {publisher!r}")

    event = Event.from_dict(payload)
    paths = secret_fields.get(event.type, ())
    masked_data, _ = mask_data(event.data, paths) if paths else (event.data, {})
    stored = event.with_data(masked_data).to_dict()

    handlers = registry.match(event.type)
    if not handlers:
        return Accepted(event, publisher, stored, "skipped", f"no handler for {event.type}")
    try:
        data_errors = schemas.validate_data(event.type, event.data, tolerant=True)
    except UnknownEventTypeError:
        return Accepted(event, publisher, stored, "skipped", f"unknown type {event.type}: no schema")
    if data_errors:
        return Rejection(422, "invalid_data", "; ".join(data_errors[:5]))
    return Accepted(
        event,
        publisher,
        stored,
        "received",
        inline=[x for x in handlers if x.inline],
        queued=[x for x in handlers if not x.inline],
    )


def log_rejection(rejection: Rejection, headers: Mapping[str, str]) -> None:
    h = lower_headers(headers)
    logger.warning(
        "rt_bus_receive_rejected",
        extra={
            "status_code": rejection.status_code,
            "reason": rejection.detail,
            "publisher": h.get(HEADER_PUBLISHER.lower()),
            "event_id": h.get(HEADER_EVENT_ID.lower()),
        },
    )
