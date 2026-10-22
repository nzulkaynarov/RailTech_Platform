"""Конверт CloudEvents 1.0 (L1) и имя типа (L2): построение, разбор, сериализация.

Проверка по JSON Schema — в `rt_bus.schemas`; здесь только структура и значения по умолчанию.
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from .context import get_correlation_id, get_traceparent, new_correlation_id, valid_correlation_id
from .errors import UnknownEventTypeError

SPECVERSION = "1.0"
DATACONTENTTYPE = "application/json"
DEFAULT_TENANT = "railtech"
SOURCE_PREFIX = "rt://"

TYPE_RE = re.compile(
    r"^uz\.railtech\.(?P<domain>crm|erp|eds|identity|platform)"
    r"\.(?P<entity>[a-z][a-z0-9_]*)\.(?P<action>[a-z][a-z0-9_]*)\.v(?P<version>[1-9][0-9]*)$"
)
#: Имя сервиса (издателя, подписчика): `crm`, `erp`, `platform-bff`, `connector-<имя>`.
SERVICE_NAME_RE = re.compile(r"^[a-z][a-z0-9-]{0,62}$")

#: Атрибуты конверта, которые не являются расширениями.
CORE_ATTRIBUTES = frozenset(
    {
        "specversion",
        "id",
        "source",
        "type",
        "time",
        "subject",
        "datacontenttype",
        "dataschema",
        "tenant",
        "correlationid",
        "traceparent",
        "data",
    }
)


@dataclass(frozen=True)
class EventType:
    """Разобранный тип `uz.railtech.<домен>.<сущность>.<действие>.v<N>`."""

    domain: str
    entity: str
    action: str
    version: int

    @property
    def name(self) -> str:
        return f"uz.railtech.{self.domain}.{self.entity}.{self.action}.v{self.version}"

    @property
    def schema_path(self) -> str:
        """Путь схемы `data` относительно каталога `events/`."""
        return f"{self.domain}/{self.entity}.{self.action}.v{self.version}.json"

    @property
    def dataschema(self) -> str:
        return f"rt://contracts/events/{self.domain}/{self.entity}.{self.action}/v{self.version}"


def parse_type(value: str) -> EventType:
    match = TYPE_RE.match(value or "")
    if match is None:
        raise UnknownEventTypeError(f"event type {value!r} is not uz.railtech.<domain>.<entity>.<action>.v<N>")
    return EventType(match["domain"], match["entity"], match["action"], int(match["version"]))


def source_for(service: str) -> str:
    return f"{SOURCE_PREFIX}{service}"


def format_time(moment: datetime) -> str:
    """RFC 3339 в UTC с суффиксом `Z` (миллисекунды)."""
    if moment.tzinfo is None:
        raise ValueError("event time must be timezone-aware")
    return moment.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_time(value: str) -> datetime:
    moment = datetime.fromisoformat(value)
    if moment.tzinfo is None:
        raise ValueError("time has no UTC offset")
    return moment


@dataclass(frozen=True)
class Event:
    """Событие в конверте CloudEvents. `data` — тело по схеме типа."""

    id: str
    source: str
    type: str
    time: str
    dataschema: str
    tenant: str
    correlationid: str
    data: dict[str, Any]
    subject: str | None = None
    traceparent: str | None = None
    extensions: Mapping[str, Any] = field(default_factory=dict)
    specversion: str = SPECVERSION
    datacontenttype: str = DATACONTENTTYPE

    @property
    def publisher(self) -> str:
        """Имя издателя из `source` (`rt://erp` → `erp`)."""
        return self.source.removeprefix(SOURCE_PREFIX)

    @property
    def event_type(self) -> EventType:
        return parse_type(self.type)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "specversion": self.specversion,
            "id": self.id,
            "source": self.source,
            "type": self.type,
            "time": self.time,
        }
        if self.subject is not None:
            out["subject"] = self.subject
        out.update(
            {
                "datacontenttype": self.datacontenttype,
                "dataschema": self.dataschema,
                "tenant": self.tenant,
                "correlationid": self.correlationid,
            }
        )
        if self.traceparent is not None:
            out["traceparent"] = self.traceparent
        for key, value in self.extensions.items():
            out.setdefault(key, value)
        out["data"] = self.data
        return out

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, separators=(",", ":"))

    def with_data(self, data: dict[str, Any]) -> Event:
        return Event(
            id=self.id,
            source=self.source,
            type=self.type,
            time=self.time,
            dataschema=self.dataschema,
            tenant=self.tenant,
            correlationid=self.correlationid,
            data=data,
            subject=self.subject,
            traceparent=self.traceparent,
            extensions=self.extensions,
            specversion=self.specversion,
            datacontenttype=self.datacontenttype,
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> Event:
        """Конверт из словаря (без проверки схемы — её делает `SchemaRegistry.validate_envelope`)."""
        data = payload.get("data")
        return cls(
            id=str(payload["id"]),
            source=str(payload["source"]),
            type=str(payload["type"]),
            time=str(payload["time"]),
            dataschema=str(payload.get("dataschema", "")),
            tenant=str(payload.get("tenant", DEFAULT_TENANT)),
            correlationid=str(payload.get("correlationid", "")),
            data=dict(data) if isinstance(data, Mapping) else {},
            subject=None if payload.get("subject") is None else str(payload["subject"]),
            traceparent=None if payload.get("traceparent") is None else str(payload["traceparent"]),
            extensions={k: v for k, v in payload.items() if k not in CORE_ATTRIBUTES},
            specversion=str(payload.get("specversion", SPECVERSION)),
            datacontenttype=str(payload.get("datacontenttype", DATACONTENTTYPE)),
        )


def new_event(
    *,
    type: str,
    data: Mapping[str, Any],
    source: str,
    subject: str | None = None,
    tenant: str = DEFAULT_TENANT,
    event_id: str | uuid.UUID | None = None,
    time: datetime | None = None,
    correlationid: str | None = None,
    traceparent: str | None = None,
) -> Event:
    """Построить событие: `id` — новый UUID, `time` — сейчас (UTC), корреляция — из аргументов или контекста."""
    event_type = parse_type(type)
    cid = valid_correlation_id(correlationid) or get_correlation_id() or new_correlation_id()
    return Event(
        id=str(event_id or uuid.uuid4()),
        source=source,
        type=event_type.name,
        time=format_time(time or datetime.now(UTC)),
        dataschema=event_type.dataschema,
        tenant=tenant,
        correlationid=cid,
        data=json.loads(json.dumps(dict(data))),
        subject=subject,
        traceparent=traceparent if traceparent is not None else get_traceparent(),
    )
