"""Подписанные доставки шины для тестов приёмника BFF: пример контракта и HMAC отправителя."""

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from rt_bus.signing import format_timestamp, sign

EVENTS = Path(__file__).resolve().parents[4] / "packages/contracts/events"
SECRET = "test-pair-secret-erp-platform-bff"
CRM_SECRET = "test-pair-secret-crm-platform-bff"


def example(domain: str, name: str) -> dict[str, Any]:
    body: dict[str, Any] = json.loads(
        (EVENTS / domain / "examples" / f"{name}.v1.json").read_text(encoding="utf-8")
    )
    return body


def envelope(domain: str, name: str, **changes: Any) -> dict[str, Any]:
    """Пример события с новым id и временем «сейчас» (окно подписи — 300 с)."""
    body = example(domain, name)
    body["id"] = str(uuid.uuid4())
    body["time"] = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    body.update(changes)
    return body


def delivery(
    body: dict[str, Any],
    *,
    publisher: str = "erp",
    secret: str = SECRET,
    timestamp: str | None = None,
) -> tuple[dict[str, str], bytes]:
    raw = json.dumps(body, ensure_ascii=False).encode()
    stamp = timestamp or format_timestamp(datetime.now(UTC))
    headers = {
        "content-type": "application/cloudevents+json",
        "x-rt-publisher": publisher,
        "x-rt-event-id": body["id"],
        "x-rt-timestamp": stamp,
        "x-rt-signature": sign(secret, body["id"], stamp, raw),
    }
    return headers, raw
