"""Коннектор «ERP» (ADR-0022, ADR-0018, M3-CRM-02): адрес, секреты и проба `GET /health`.

Порядок чтения — как у токена бота: запись из «Подключений» (адрес — `settings.integrations`,
секреты — `integration_secrets`), иначе `.env` (`ERP_BASE_URL`, `ERP_SERVICE_TOKEN`,
`ERP_WEBHOOK_SECRET`). Коннектор «настроен» = есть адрес и сервисный токен; тогда жизненный цикл
работает в режиме `erp` (`domain/backoffice.py`). Сам клиент ERP (handoff, зеркало сделок,
приёмник вебхуков) — M3-CRM-03/04. Значения секретов не логируются.
"""

import time
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

import httpx
import structlog
from pydantic import BaseModel, ConfigDict, ValidationError

from app.config import Settings
from app.domain.erp_connector import base_url_problem, health_url, normalize_base_url
from app.security.secrets_store import ERP_SERVICE_TOKEN, ERP_WEBHOOK_SECRET, SecretsStore
from app.services.settings import SettingsService

logger = structlog.get_logger(__name__)

Source = Literal["db", "env", "none"]
ErpErrorKind = Literal["invalid_url", "unauthorized", "unavailable", "bad_response"]
HEALTH_TIMEOUT_S = 5.0


@dataclass(frozen=True, slots=True)
class ErpConnection:
    base_url: str
    token: str


@dataclass(frozen=True, slots=True)
class ErpResolution:
    """Откуда взяты адрес и секреты (для «Подключений»); сами значения — только в процессе."""

    base_url: str
    base_url_source: Source
    token: str
    token_source: Source
    webhook_secret: str
    webhook_secret_source: Source

    @property
    def connection(self) -> ErpConnection | None:
        if self.base_url and self.token:
            return ErpConnection(base_url=self.base_url, token=self.token)
        return None


async def _stored(store: SecretsStore, key: str) -> str:
    if not store.enabled:
        return ""
    try:
        return await store.get(key) or ""
    except Exception:
        logger.warning("erp_secret_db_unavailable", key=key, exc_info=True)
        return ""


async def _stored_base_url(settings: SettingsService | None) -> str:
    if settings is None:
        return ""
    try:
        return (await settings.get()).integrations.erp_base_url
    except Exception:
        logger.warning("erp_base_url_db_unavailable", exc_info=True)
        return ""


def _pick(db_value: str, env_value: str) -> tuple[str, Source]:
    if db_value:
        return db_value, "db"
    return (env_value, "env") if env_value else ("", "none")


async def resolve_erp(
    store: SecretsStore, config: Settings, settings: SettingsService | None = None
) -> ErpResolution:
    """Адрес и секреты с источниками: БД («Подключения») → env; сбой БД → env."""
    base_url, base_source = _pick(
        normalize_base_url(await _stored_base_url(settings)),
        normalize_base_url(config.erp_base_url),
    )
    token, token_source = _pick(
        await _stored(store, ERP_SERVICE_TOKEN), config.erp_service_token.get_secret_value()
    )
    webhook, webhook_source = _pick(
        await _stored(store, ERP_WEBHOOK_SECRET), config.erp_webhook_secret.get_secret_value()
    )
    return ErpResolution(base_url, base_source, token, token_source, webhook, webhook_source)


async def resolve_connection(
    store: SecretsStore, config: Settings, settings: SettingsService | None = None
) -> ErpConnection | None:
    """Адрес и токен ERP; нет любого из них — коннектор не настроен."""
    return (await resolve_erp(store, config, settings)).connection


async def erp_connector_configured(
    store: SecretsStore, config: Settings, settings: SettingsService | None = None
) -> bool:
    """Единственная точка проверки для режима жизненного цикла (`backoffice_mode`)."""
    return await resolve_connection(store, config, settings) is not None


class ErpProbeError(Exception):
    """Проверка связи не удалась; `kind` — стабильный класс причины, `detail` — для логов/экрана."""

    def __init__(self, kind: ErpErrorKind, detail: str = "") -> None:
        super().__init__(f"{kind}: {detail}" if detail else kind)
        self.kind: ErpErrorKind = kind
        self.detail = detail


@dataclass(frozen=True, slots=True)
class ErpHealth:
    """Ответ `GET /api/integration/v1/health` (схема `Health` контракта) и время ответа."""

    status: Literal["ok", "degraded"]
    version: str
    migrations_applied: bool
    queue_alive: bool
    checked_at: datetime
    latency_ms: int


class _HealthPayload(BaseModel):
    """Схема `Health` из `packages/contracts/openapi/erp-integration.yaml`."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["ok", "degraded"]
    version: str
    migrations_applied: bool
    queue_alive: bool
    checked_at: datetime


class ErpProbe(Protocol):
    async def health(self, connection: ErpConnection) -> ErpHealth: ...


class HttpxErpProbe:
    """`GET {base_url}/api/integration/v1/health` с сервисным токеном, таймаут 5 с."""

    def __init__(self, timeout_s: float = HEALTH_TIMEOUT_S) -> None:
        self._timeout_s = timeout_s

    async def health(self, connection: ErpConnection) -> ErpHealth:
        problem = base_url_problem(connection.base_url)
        if problem is not None:
            raise ErpProbeError("invalid_url", problem)
        headers = {"Authorization": f"Bearer {connection.token}", "Accept": "application/json"}
        started = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=self._timeout_s) as client:
                response = await client.get(health_url(connection.base_url), headers=headers)
        except httpx.TimeoutException as exc:
            raise ErpProbeError("unavailable", "timeout") from exc
        except httpx.InvalidURL as exc:
            raise ErpProbeError("invalid_url", str(exc)) from exc
        except httpx.HTTPError as exc:
            raise ErpProbeError("unavailable", type(exc).__name__) from exc
        latency_ms = int((time.monotonic() - started) * 1000)
        return _parse(response, latency_ms)


def _parse(response: httpx.Response, latency_ms: int) -> ErpHealth:
    if response.status_code in (401, 403):
        raise ErpProbeError("unauthorized", f"HTTP {response.status_code}")
    if response.status_code != 200:
        raise ErpProbeError("bad_response", f"HTTP {response.status_code}")
    try:
        payload = _HealthPayload.model_validate_json(response.content)
    except ValidationError as exc:
        raise ErpProbeError("bad_response", f"schema: {exc.error_count()} errors") from exc
    return ErpHealth(
        status=payload.status,
        version=payload.version,
        migrations_applied=payload.migrations_applied,
        queue_alive=payload.queue_alive,
        checked_at=payload.checked_at,
        latency_ms=latency_ms,
    )
