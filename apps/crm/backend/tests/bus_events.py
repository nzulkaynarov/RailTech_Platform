"""Контракт событий rt_bus как источник тестовых данных CRM (B4): примеры и подписанные запросы.

Один источник с ERP и самой шиной: примеры полного конверта лежат в
`packages/contracts/events/<домен>/examples/<сущность>.<действие>.v<N>.json`, схемы — рядом.
Копий схем и примеров в тестах CRM нет.
"""

import copy
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from rt_bus.signing import signed_headers
from rt_contracts.events import TYPES

REPO = Path(__file__).resolve().parents[4]
EVENTS_DIR = REPO / "packages" / "contracts" / "events"

#: Тестовый секрет вебхуков сопряжения; секреты пар шины выводятся из него (L12).
WEBHOOK_SECRET = "bus-test-webhook-secret-0001"


def event_types(domain: str) -> list[str]:
    """Типы событий домена из каталога контракта (`uz.railtech.<домен>.….v1`)."""
    prefix = f"uz.railtech.{domain}."
    return sorted(t for t in TYPES if t.startswith(prefix))


def _example_path(event_type: str) -> Path:
    parts = event_type.split(".")  # uz railtech <домен> <сущность> <действие> v1
    domain, entity, action, version = parts[2], parts[3], parts[4], parts[5]
    return EVENTS_DIR / domain / "examples" / f"{entity}.{action}.{version}.json"


def example_envelope(event_type: str) -> dict[str, Any]:
    """Пример полного конверта из контракта; копия — менять можно."""
    return copy.deepcopy(json.loads(_example_path(event_type).read_text(encoding="utf-8")))


def example_data(event_type: str) -> dict[str, Any]:
    data: dict[str, Any] = example_envelope(event_type)["data"]
    return data


def example_types(domain: str) -> list[str]:
    return [t for t in event_types(domain) if _example_path(t).exists()]


def envelope_for(
    event_type: str,
    data: dict[str, Any],
    *,
    source: str = "rt://erp",
    time: datetime | None = None,
    event_id: str | None = None,
    correlationid: str | None = None,
    traceparent: str | None = None,
) -> dict[str, Any]:
    """Конверт CloudEvents (L1) вокруг `data`."""
    parts = event_type.split(".")
    envelope: dict[str, Any] = {
        "specversion": "1.0",
        "id": event_id or str(uuid.uuid4()),
        "source": source,
        "type": event_type,
        "time": (time or datetime.now(UTC)).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
        "datacontenttype": "application/json",
        "dataschema": f"rt://contracts/events/{parts[2]}/{parts[3]}.{parts[4]}/{parts[5]}",
        "tenant": "railtech",
        "correlationid": correlationid or str(uuid.uuid4()),
        "data": data,
    }
    if traceparent:
        envelope["traceparent"] = traceparent
    return envelope


def signed_raw(
    body: bytes,
    event_id: str,
    secret: str,
    *,
    publisher: str = "erp",
    now: datetime | None = None,
    correlation_id: str | None = None,
    traceparent: str | None = None,
) -> dict[str, str]:
    """Заголовки доставки для произвольного тела (HMAC v2, L3)."""
    return signed_headers(
        publisher=publisher,
        event_id=event_id,
        body=body,
        secret=secret,
        now=now or datetime.now(UTC),
        correlation_id=correlation_id,
        traceparent=traceparent,
    )


def signed_request(
    envelope: dict[str, Any],
    secret: str,
    *,
    publisher: str = "erp",
    now: datetime | None = None,
) -> tuple[dict[str, str], bytes]:
    """Заголовки и тело доставки, подписанные как издатель шины (HMAC v2, L3)."""
    body = json.dumps(envelope, ensure_ascii=False).encode()
    headers = signed_raw(
        body,
        envelope["id"],
        secret,
        publisher=publisher,
        now=now,
        correlation_id=envelope.get("correlationid"),
        traceparent=envelope.get("traceparent"),
    )
    return headers, body
