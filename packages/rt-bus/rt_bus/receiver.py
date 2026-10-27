"""Приёмник `POST /bus/v1/events` без фреймворка: подпись и окно → разбор конверта → решение (L3, L10).

Хранение в inbox и вызов обработчиков делают адаптеры (SQLAlchemy, Django, память); тонкие обёртки — `rt_bus.fastapi`
и `rt_bus.django.views`.

Ответы: 200 — принято (новое, повтор `id`, `skipped`); 401 — нет или неверная подпись, неизвестный издатель, вне окна,
`source` не совпадает с издателем; 400 — не JSON, не конверт, `id` не совпадает с заголовком, домен типа не принадлежит
издателю (`foreign_type`: повтор не поможет, предохранитель подписчика не затрагивается); 422 — `data` известного
типа не по схеме (терпимо: `additionalProperties` не отказ); 503 — inline-обработчик упал (издатель повторит).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from .envelope import SERVICE_NAME_RE, TYPE_RE, Event, source_for
from .errors import UnknownEventTypeError
from .handlers import Handler, HandlerRegistry
from .masking import mask_data, redact
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

#: Каких доменов типа (`uz.railtech.<домен>.…`) издатель вправе публиковать (L2): сотрудник — домен `identity`,
#: источник — CRM (ADR-0015). Издателя нет в таблице — только домен с его именем. Свой набор —
#: `BusConfig.publisher_domains`.
DEFAULT_PUBLISHER_DOMAINS: Mapping[str, frozenset[str]] = {
    "crm": frozenset({"crm", "identity"}),
    "erp": frozenset({"erp"}),
    "eds": frozenset({"eds"}),
    "platform-bff": frozenset({"platform"}),
}


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


def foreign_type(publisher: str, event_type: str, publisher_domains: Mapping[str, frozenset[str]] | None) -> str | None:
    """Тип `uz.railtech.<домен>.…` должен принадлежать издателю пары (подпись пары): CRM публикует `crm` и `identity`,
    ERP — `erp`, EDS — `eds`, BFF — `platform`. Издателя нет в таблице — только домен с его именем. Возвращает причину
    отказа или `None`."""
    match = TYPE_RE.match(event_type)
    if match is None:
        return f"type {event_type!r} is not uz.railtech.<domain>.<entity>.<action>.v<N>"
    allowed = (DEFAULT_PUBLISHER_DOMAINS if publisher_domains is None else publisher_domains).get(
        publisher, frozenset({publisher})
    )
    if match["domain"] in allowed:
        return None
    return f"type {event_type!r}: domain {match['domain']!r} does not belong to publisher {publisher!r}"


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
    publisher_domains: Mapping[str, frozenset[str]] | None = None,
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

    foreign = foreign_type(publisher, str(payload["type"]), publisher_domains)
    if foreign is not None:
        return Rejection(400, "foreign_type", foreign)

    event = Event.from_dict(payload)
    paths = secret_fields.get(event.type, ())
    masked_data, secret_values = mask_data(event.data, paths) if paths else (event.data, {})
    stored = event.with_data(masked_data).to_dict()

    handlers = registry.match(event.type)
    if not handlers:
        return Accepted(event, publisher, stored, "skipped", f"no handler for {event.type}")
    try:
        data_errors = schemas.validate_data(event.type, event.data, tolerant=True)
    except UnknownEventTypeError:
        return Accepted(event, publisher, stored, "skipped", f"unknown type {event.type}: no schema")
    if data_errors:
        return Rejection(422, "invalid_data", "; ".join(redact(data_errors[:5], secret_values)))
    return Accepted(
        event,
        publisher,
        stored,
        "received",
        inline=[x for x in handlers if x.inline],
        queued=[x for x in handlers if not x.inline],
    )


#: Отказы, текст которых содержит значения из тела события (сообщения схемы цитируют их): в журнал уходит
#: только код отказа — персональные данные в логах недопустимы (SPEC §11).
_DETAIL_HAS_VALUES = frozenset({"invalid_data", "invalid_envelope"})


def log_rejection(rejection: Rejection, headers: Mapping[str, str]) -> None:
    h = lower_headers(headers)
    logger.warning(
        "rt_bus_receive_rejected",
        extra={
            "status_code": rejection.status_code,
            "reason": rejection.error if rejection.error in _DETAIL_HAS_VALUES else rejection.detail,
            "publisher": h.get(HEADER_PUBLISHER.lower()),
            "event_id": h.get(HEADER_EVENT_ID.lower()),
        },
    )
