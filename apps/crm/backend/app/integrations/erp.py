"""Коннектор «ERP» (ADR-0022, ADR-0018, M3-CRM-02): адрес, секреты и проба `GET /health`.

Порядок чтения — как у токена бота: запись из «Подключений» (адрес — `settings.integrations`,
секреты — `integration_secrets`), иначе `.env` (`ERP_BASE_URL`, `ERP_SERVICE_TOKEN`,
`ERP_WEBHOOK_SECRET`). Коннектор «настроен» = есть адрес и сервисный токен; тогда жизненный цикл
работает в режиме `erp` (`domain/backoffice.py`). Сам клиент ERP (handoff, зеркало сделок,
приёмник вебхуков) — M3-CRM-03/04. Значения секретов не логируются.
"""

import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

import httpx
import structlog
from pydantic import BaseModel, ConfigDict, ValidationError

from app.config import Settings
from app.domain.erp_connector import base_url_problem, health_url, normalize_base_url
from app.domain.errors import (
    ConflictError,
    Reason,
    UpstreamUnavailableError,
    ValidationFailedError,
)
from app.security.secrets_store import (
    ERP_SERVICE_TOKEN,
    ERP_WEBHOOK_SECRET,
    ERP_WEBHOOK_SECRET_PREVIOUS,
    SecretsStore,
)
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
    # Предыдущий секрет вебхуков (ротация без простоя, FIX-35): принимается наравне с текущим,
    # пока его не сняли.
    webhook_secret_previous: str = ""
    webhook_secret_previous_source: Source = "none"  # noqa: S105 — источник, не секрет

    @property
    def webhook_secrets(self) -> tuple[str, ...]:
        """Секреты для проверки подписи: текущий, затем предыдущий (без пустых и повторов)."""
        seen: dict[str, None] = {}
        for value in (self.webhook_secret, self.webhook_secret_previous):
            if value:
                seen.setdefault(value)
        return tuple(seen)

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


async def _previous_secret_until(settings: SettingsService | None) -> datetime | None:
    """Срок приёма предыдущего секрета после «Обновить ключи» (M3-CRM-10); пусто — срока нет."""
    if settings is None:
        return None
    try:
        return (await settings.get()).integrations.erp_previous_secret_until
    except Exception:
        logger.warning("erp_previous_secret_until_db_unavailable", exc_info=True)
        return None


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
    # Секрет вебхуков: «Подключения» (БД) → `.env` (`ERP_WEBHOOK_SECRET`; допускается список через
    # запятую, как у сервисных токенов: первый — текущий, второй — предыдущий). Предыдущий секрет
    # из БД перекрывает второе значение `.env`.
    env_secrets = [
        v.strip() for v in config.erp_webhook_secret.get_secret_value().split(",") if v.strip()
    ]
    stored_current = await _stored(store, ERP_WEBHOOK_SECRET)
    stored_previous = await _stored(store, ERP_WEBHOOK_SECRET_PREVIOUS)
    webhook, webhook_source = _pick(stored_current, env_secrets[0] if env_secrets else "")
    previous = ""
    previous_source: Source = "none"
    until = await _previous_secret_until(settings)
    if stored_previous and until is not None and until <= datetime.now(UTC):
        # Переход после «Обновить ключи» закончился: предыдущий секрет не принимается уже при приёме
        # события, а не когда его удалит проверка связи.
        stored_previous = ""
    if stored_previous:
        previous, previous_source = stored_previous, "db"
    elif not stored_current and len(env_secrets) > 1:
        previous, previous_source = env_secrets[1], "env"
    return ErpResolution(
        base_url,
        base_source,
        token,
        token_source,
        webhook,
        webhook_source,
        previous,
        previous_source,
    )


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


@dataclass(frozen=True, slots=True)
class HandoffCompanyPayload:
    name: str
    inn: str = ""
    segment: str = ""
    language: str = "ru"


@dataclass(frozen=True, slots=True)
class HandoffContactPayload:
    crm_contact_id: int
    name: str
    language: str
    is_primary: bool
    preferred_channel: str
    phone: str = ""
    email: str = ""
    telegram_user_id: int | None = None


@dataclass(frozen=True, slots=True)
class HandoffNeedPayload:
    summary: str
    product_interest: list[str] = field(default_factory=list)
    attachments: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class HandoffOwnerPayload:
    crm_user_id: int
    name: str


@dataclass(frozen=True, slots=True)
class HandoffConsentPayload:
    given_at: str
    version: str = "1.0"


@dataclass(frozen=True, slots=True)
class HandoffInvitePayload:
    channels: list[str] = field(default_factory=lambda: ["telegram"])


@dataclass(frozen=True, slots=True)
class HandoffPayload:
    crm_client_id: int
    company: HandoffCompanyPayload
    contacts: list[HandoffContactPayload]
    need: HandoffNeedPayload
    owner: HandoffOwnerPayload
    consent: HandoffConsentPayload
    create_request: bool = True
    invite: HandoffInvitePayload = field(default_factory=HandoffInvitePayload)
    crm_lead_id: int | None = None


@dataclass(frozen=True, slots=True)
class HandoffResult:
    erp_company_id: int
    erp_request_id: int | None
    invite_sent_via: list[str]
    cabinet_url: str


def handoff_payload_to_dict(p: HandoffPayload) -> dict[str, Any]:
    return {
        "crm_client_id": p.crm_client_id,
        "crm_lead_id": p.crm_lead_id,
        "company": {
            "name": p.company.name,
            "inn": p.company.inn or "",
            "segment": p.company.segment or "",
            "language": p.company.language,
        },
        "contacts": [
            {
                "crm_contact_id": c.crm_contact_id,
                "name": c.name,
                "phone": c.phone or "",
                "email": c.email or "",
                "telegram_user_id": c.telegram_user_id,
                "language": c.language,
                "is_primary": c.is_primary,
                "preferred_channel": c.preferred_channel,
            }
            for c in p.contacts
        ],
        "need": {
            "summary": p.need.summary,
            "product_interest": p.need.product_interest,
            "attachments": p.need.attachments,
        },
        "owner": {
            "crm_user_id": p.owner.crm_user_id,
            "name": p.owner.name,
        },
        "consent": {
            "given_at": p.consent.given_at,
            "version": p.consent.version,
        },
        "create_request": p.create_request,
        "invite": {
            "channels": p.invite.channels,
        },
    }


class ErpClient(Protocol):
    async def handoff_client(
        self, payload: HandoffPayload, *, idempotency_key: str | None = None
    ) -> HandoffResult: ...


def _handoff_conflict(response: httpx.Response) -> ConflictError:
    """409 передачи: `INN_CONFLICT` — ИНН уже у другого клиента CRM в ERP; повтор не поможет."""
    try:
        detail = str(response.json().get("detail", ""))
    except (ValueError, AttributeError):
        detail = ""
    if detail == "INN_CONFLICT":
        return ConflictError(
            "erp: inn belongs to a company linked to another crm client",
            reason=Reason.ERP_INN_CONFLICT,
        )
    return ConflictError(
        f"erp conflict: {detail or response.text[:200]}", reason=Reason.ERP_BAD_RESPONSE
    )


class HttpxErpClient:
    """HTTP-клиент к API интеграции ERP (`POST /api/integration/v1/clients/handoff` и др.)."""

    def __init__(
        self,
        store: SecretsStore,
        config: Settings,
        settings: SettingsService | None = None,
        *,
        timeout_s: float = 10.0,
    ) -> None:
        self._store = store
        self._config = config
        self._settings = settings
        self._timeout_s = timeout_s

    async def handoff_client(
        self, payload: HandoffPayload, *, idempotency_key: str | None = None
    ) -> HandoffResult:
        connection = await resolve_connection(self._store, self._config, self._settings)
        if connection is None:
            raise ConflictError("erp connector is not configured", reason=Reason.ERP_NOT_CONFIGURED)
        problem = base_url_problem(connection.base_url)
        if problem is not None:
            raise ValidationFailedError(
                f"erp base url is invalid: {problem}",
                reason=Reason.ERP_INVALID_URL,
                field="base_url",
            )
        idem_key = idempotency_key or str(uuid.uuid4())
        headers = {
            "Authorization": f"Bearer {connection.token}",
            "Idempotency-Key": idem_key,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        body = handoff_payload_to_dict(payload)
        url = f"{connection.base_url.rstrip('/')}/api/integration/v1/clients/handoff"
        try:
            async with httpx.AsyncClient(timeout=self._timeout_s) as client:
                response = await client.post(url, json=body, headers=headers)
        except httpx.TimeoutException as exc:
            raise UpstreamUnavailableError("erp timeout", reason=Reason.ERP_UNAVAILABLE) from exc
        except httpx.InvalidURL as exc:
            raise ValidationFailedError(
                str(exc), reason=Reason.ERP_INVALID_URL, field="base_url"
            ) from exc
        except httpx.HTTPError as exc:
            raise UpstreamUnavailableError(
                type(exc).__name__, reason=Reason.ERP_UNAVAILABLE
            ) from exc

        if response.status_code in (401, 403):
            raise UpstreamUnavailableError(
                f"HTTP {response.status_code}", reason=Reason.ERP_UNAUTHORIZED
            )
        if response.status_code == 409:
            raise _handoff_conflict(response)
        if response.status_code == 422:
            raise ValidationFailedError(
                f"erp validation error: {response.text[:300]}",
                reason=Reason.ERP_BAD_RESPONSE,
            )
        if response.status_code not in (200, 201):
            raise UpstreamUnavailableError(
                f"erp bad response: HTTP {response.status_code}",
                reason=Reason.ERP_BAD_RESPONSE,
            )

        try:
            data = response.json()
            return HandoffResult(
                erp_company_id=data["erp_company_id"],
                erp_request_id=data.get("erp_request_id"),
                invite_sent_via=data.get("invite", {}).get("sent_via", []),
                cabinet_url=data.get("invite", {}).get("cabinet_url", ""),
            )
        except Exception as exc:
            raise UpstreamUnavailableError(
                f"bad json from erp: {exc}", reason=Reason.ERP_BAD_RESPONSE
            ) from exc
