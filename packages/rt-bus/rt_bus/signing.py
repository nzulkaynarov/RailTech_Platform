"""Подпись доставки HMAC v2 (L3, L4).

`X-RT-Signature: sha256=<hex HMAC-SHA256(secret, f"{X-RT-Event-Id}.{X-RT-Timestamp}.{raw_body}")>`; метка — момент
попытки (каждый повтор подписывается заново); приёмник проверяет окно `|now − X-RT-Timestamp| ≤ 300 с` и принимает любой
из действующих секретов пары. Секрет пары «издатель → подписчик» — `RT_BUS_SECRET_<ИЗДАТЕЛЬ>_<ПОДПИСЧИК>` (список через
запятую: первым подписывают, принимают любой); сервис может подставить свой поставщик (сопряжение в БД).
"""

from __future__ import annotations

import hashlib
import hmac
import os
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime

HEADER_PUBLISHER = "X-RT-Publisher"
HEADER_EVENT_ID = "X-RT-Event-Id"
HEADER_TIMESTAMP = "X-RT-Timestamp"
HEADER_SIGNATURE = "X-RT-Signature"
CONTENT_TYPE = "application/cloudevents+json"
SIGNATURE_PREFIX = "sha256="
DEFAULT_WINDOW_SECONDS = 300.0

#: Поставщик секретов пары: (издатель, подписчик) → действующие секреты, первый — для подписи.
SecretProvider = Callable[[str, str], Sequence[str]]


def secret_env_name(publisher: str, subscriber: str) -> str:
    """`RT_BUS_SECRET_<ИЗДАТЕЛЬ>_<ПОДПИСЧИК>`: верхний регистр, `-` → `_`."""
    return f"RT_BUS_SECRET_{publisher}_{subscriber}".upper().replace("-", "_")


def split_secrets(raw: str | None) -> list[str]:
    return [part.strip() for part in (raw or "").split(",") if part.strip()]


def env_secrets(publisher: str, subscriber: str) -> list[str]:
    """Поставщик по умолчанию: секреты пары из окружения."""
    return split_secrets(os.environ.get(secret_env_name(publisher, subscriber)))


def static_secrets(pairs: Mapping[tuple[str, str], str | Sequence[str]]) -> SecretProvider:
    """Поставщик из словаря `{(издатель, подписчик): "s1,s2" | [s1, s2]}` — для тестов и встраивания."""

    def provider(publisher: str, subscriber: str) -> list[str]:
        value = pairs.get((publisher, subscriber))
        if value is None:
            return []
        return split_secrets(value) if isinstance(value, str) else [s for s in value if s]

    return provider


def format_timestamp(moment: datetime) -> str:
    """`X-RT-Timestamp`: UTC ISO 8601 с `Z`, до секунды."""
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def sign(secret: str, event_id: str, timestamp: str, body: bytes) -> str:
    message = f"{event_id}.{timestamp}.".encode() + body
    return SIGNATURE_PREFIX + hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def verify(secrets: Sequence[str], event_id: str, timestamp: str, body: bytes, signature: str) -> bool:
    """Подпись верна хотя бы для одного секрета; сравнение constant-time, проверяются все секреты."""
    given = (signature or "").strip().encode()
    matched = False
    for secret in secrets:
        if not secret:
            continue
        expected = sign(secret, event_id, timestamp, body).encode()
        matched |= hmac.compare_digest(expected, given)
    return matched


def window_problem(timestamp: str, now: datetime, window_seconds: float = DEFAULT_WINDOW_SECONDS) -> str | None:
    """Почему метка не годится (`None` — годится): не ISO 8601, без пояса, вне окна."""
    try:
        moment = datetime.fromisoformat((timestamp or "").strip())
    except ValueError:
        return "X-RT-Timestamp is not ISO 8601"
    if moment.tzinfo is None:
        return "X-RT-Timestamp has no UTC offset"
    skew = abs((now - moment).total_seconds())
    if skew > window_seconds:
        return f"X-RT-Timestamp is {int(skew)} s away from now (window {int(window_seconds)} s)"
    return None


def signed_headers(
    *,
    publisher: str,
    event_id: str,
    body: bytes,
    secret: str,
    now: datetime,
    correlation_id: str | None = None,
    traceparent: str | None = None,
) -> dict[str, str]:
    """Заголовки попытки доставки (L3)."""
    timestamp = format_timestamp(now)
    headers = {
        "Content-Type": CONTENT_TYPE,
        HEADER_PUBLISHER: publisher,
        HEADER_EVENT_ID: event_id,
        HEADER_TIMESTAMP: timestamp,
        HEADER_SIGNATURE: sign(secret, event_id, timestamp, body),
    }
    if traceparent:
        headers["traceparent"] = traceparent
    if correlation_id:
        headers["X-Request-ID"] = correlation_id
    return headers
