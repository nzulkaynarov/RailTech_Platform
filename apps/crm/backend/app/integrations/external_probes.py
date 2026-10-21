"""Пробы внешних сервисов для центра внешних сервисов (M3-CRM-12, ADR-0024) — без платных вызовов.

Telegram — прямым HTTP к Bot API (`getMe`, `getWebhookInfo`): токен только в пути запроса, в логи
и ошибки не попадает (логируется лишь класс исключения). Health — `GET` без тела. TLS — рукопожатие
с проверкой цепочки и чтение `notAfter`. Каждая проба ограничена таймаутом клиента.
"""

import asyncio
import contextlib
import re
import ssl
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

import httpx
import structlog

from app.domain.external_status import HttpFacts, ProbeError

logger = structlog.get_logger(__name__)
TELEGRAM_API = "https://api.telegram.org"
TLS_TIMEOUT_S = 8.0


def _ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def _kind(exc: httpx.HTTPError) -> ProbeError:
    return "timeout" if isinstance(exc, httpx.TimeoutException) else "unavailable"


async def http_health(
    client: httpx.AsyncClient, url: str, headers: dict[str, str] | None = None
) -> HttpFacts:
    """`GET url`: 2xx — ответ получен; 401/403 — `unauthorized`; иначе класс ошибки и код."""
    started = time.monotonic()
    try:
        response = await client.get(url, headers=headers)
    except httpx.HTTPError as exc:
        logger.info("external_probe_failed", error=type(exc).__name__)
        return HttpFacts(_kind(exc), type(exc).__name__, _ms(started))
    if response.status_code in (401, 403):
        return HttpFacts("unauthorized", f"HTTP {response.status_code}", _ms(started))
    if response.status_code >= 400:
        return HttpFacts("bad_response", f"HTTP {response.status_code}", _ms(started))
    return HttpFacts(None, None, _ms(started))


@dataclass(frozen=True, slots=True)
class TelegramProbe:
    error: ProbeError | None
    detail: str | None = None
    username: str | None = None
    pending_updates: int | None = None
    webhook_url: str | None = None
    last_error_message: str | None = None
    last_error_at: datetime | None = None
    latency_ms: int | None = None
    # getWebhookInfo не удался (не 2xx или `ok=false`): адрес вебхука неизвестен, а не «пуст».
    webhook_error: str | None = None


_TOKEN_IN_TEXT = re.compile(r"bot\d+:[\w-]+")


def _scrub(text: str | None, token: str) -> str | None:
    """Токен бота (и вид `bot<id>:<секрет>`) не доходит ни до метрик, ни до UI, ни до логов."""
    if text is None:
        return None
    return _TOKEN_IN_TEXT.sub("[скрыто]", text).replace(token, "[скрыто]")


def _public_url(raw: object) -> str | None:
    """Адрес вебхука без логина, query и fragment: в UI попадает только схема, хост и путь."""
    if not isinstance(raw, str) or not raw:
        return None
    try:
        parts = urlsplit(raw)
    except ValueError:
        return None
    if not parts.hostname:
        return _str(raw)
    port = f":{parts.port}" if parts.port else ""
    return _str(f"{parts.scheme}://{parts.hostname}{port}{parts.path}")


async def telegram(
    client: httpx.AsyncClient, token: str, base: str = TELEGRAM_API
) -> TelegramProbe:
    """`getMe` + `getWebhookInfo`. 401/404 — токен не принят (как `AiogramProbe`)."""
    started = time.monotonic()
    try:
        me = await client.get(f"{base}/bot{token}/getMe")
        if me.status_code in (401, 404):
            return TelegramProbe(
                "unauthorized", f"getMe: HTTP {me.status_code}", latency_ms=_ms(started)
            )
        if me.status_code >= 400:
            return TelegramProbe(
                "bad_response", f"getMe: HTTP {me.status_code}", latency_ms=_ms(started)
            )
        latency = _ms(started)
        hook = await client.get(f"{base}/bot{token}/getWebhookInfo")
    except httpx.HTTPError as exc:
        logger.info("telegram_probe_failed", error=type(exc).__name__)
        return TelegramProbe(_kind(exc), type(exc).__name__, latency_ms=_ms(started))
    username = _result(me).get("username")
    webhook_error = _webhook_info_error(hook)
    info = _result(hook) if webhook_error is None else {}
    error_date = info.get("last_error_date")
    return TelegramProbe(
        error=None,
        username=username if isinstance(username, str) else None,
        pending_updates=_int(info.get("pending_update_count")),
        webhook_url=_public_url(info.get("url")),
        last_error_message=_scrub(_str(info.get("last_error_message")), token),
        last_error_at=datetime.fromtimestamp(error_date, UTC)
        if isinstance(error_date, int)
        else None,
        latency_ms=latency,
        webhook_error=webhook_error,
    )


def _webhook_info_error(response: httpx.Response) -> str | None:
    if response.status_code >= 400:
        return f"getWebhookInfo: HTTP {response.status_code}"
    try:
        body = response.json()
    except ValueError:
        return "getWebhookInfo: ответ не разобран"
    if not isinstance(body, dict) or body.get("ok") is not True:
        return "getWebhookInfo: ok=false"
    return None


async def langfuse(
    client: httpx.AsyncClient, host: str, public_key: str, secret_key: str
) -> tuple[HttpFacts, bool | None]:
    """`/api/public/health` и `/api/public/projects` с ключами (Basic): без записи трейса."""
    base = host.rstrip("/")
    health = await http_health(client, f"{base}/api/public/health")
    if health.error is not None:
        return health, None
    try:
        response = await client.get(f"{base}/api/public/projects", auth=(public_key, secret_key))
    except httpx.HTTPError as exc:
        logger.info("langfuse_probe_failed", error=type(exc).__name__)
        return health, None
    if response.status_code in (401, 403):
        return health, False
    return health, response.status_code < 400


@dataclass(frozen=True, slots=True)
class TlsProbe:
    not_after: datetime | None
    error: str | None = None
    detail: str | None = None


async def tls(host: str, port: int = 443, timeout_s: float = TLS_TIMEOUT_S) -> TlsProbe:
    """Рукопожатие с проверкой цепочки и имени; срок — из `notAfter` сертификата сервера."""
    context = ssl.create_default_context()
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port, ssl=context, server_hostname=host), timeout_s
        )
    except ssl.SSLCertVerificationError as exc:
        return TlsProbe(None, "invalid", (exc.verify_message or type(exc).__name__)[:200])
    except (TimeoutError, OSError) as exc:
        return TlsProbe(None, "unavailable", type(exc).__name__)
    try:
        cert: dict[str, Any] = writer.get_extra_info("peercert") or {}
    finally:
        writer.close()
        with contextlib.suppress(OSError, ssl.SSLError, TimeoutError):
            await asyncio.wait_for(writer.wait_closed(), timeout_s)
    raw = cert.get("notAfter")
    if not isinstance(raw, str):
        return TlsProbe(None, "invalid", "no notAfter")
    return TlsProbe(datetime.fromtimestamp(ssl.cert_time_to_seconds(raw), UTC))


def _result(response: httpx.Response) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError:
        return {}
    result = body.get("result") if isinstance(body, dict) else None
    return result if isinstance(result, dict) else {}


def _int(raw: object) -> int | None:
    return raw if isinstance(raw, int) and not isinstance(raw, bool) else None


def _str(raw: object) -> str | None:
    return raw[:200] if isinstance(raw, str) and raw else None
