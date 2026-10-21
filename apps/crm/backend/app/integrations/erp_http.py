"""Общий HTTP-слой клиентов API интеграции ERP (`/api/integration/v1/*`): адрес, токен, ошибки.

Один порядок чтения адреса и токена («Подключения» → `.env`), одно соответствие ответов ошибкам:
429 (лимит сервисного токена, шов 0.3.0) — `ErpRateLimitedError` с паузой из `Retry-After`;
401/403 — `ERP_UNAUTHORIZED`; сеть и таймаут — `ERP_UNAVAILABLE`. Значения секретов не логируются.
"""

from typing import Any

import httpx

from app.config import Settings
from app.domain.erp_connector import INTEGRATION_PREFIX, base_url_problem
from app.domain.errors import (
    ConflictError,
    Reason,
    UpstreamUnavailableError,
    ValidationFailedError,
)
from app.integrations.erp import ErpConnection, rate_limited, resolve_connection
from app.security.secrets_store import SecretsStore
from app.services.settings import SettingsService


class ErpIntegrationHttp:
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

    async def _connection(self) -> ErpConnection:
        # Клиент работает в воркере, а коннектор сохраняют в API (другой процесс): TTL-кэш настроек
        # воркера не знает о сохранении. Сбрасываем перед чтением — задача видит текущий адрес ERP
        # (FIX-11b); секреты `SecretsStore` не кэширует.
        if self._settings is not None:
            self._settings.invalidate()
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
        return connection

    async def _send(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        connection = await self._connection()
        headers = {
            "Authorization": f"Bearer {connection.token}",
            "Accept": "application/json",
            **(extra_headers or {}),
        }
        url = f"{connection.base_url.rstrip('/')}{INTEGRATION_PREFIX}{path}"
        try:
            async with httpx.AsyncClient(timeout=self._timeout_s) as client:
                response = await client.request(method, url, json=json, headers=headers)
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
        if response.status_code == 429:
            raise rate_limited(response)
        if response.status_code in (401, 403):
            raise UpstreamUnavailableError(
                f"HTTP {response.status_code}", reason=Reason.ERP_UNAUTHORIZED
            )
        return response


def _bad_response(response: httpx.Response) -> UpstreamUnavailableError:
    return UpstreamUnavailableError(
        f"erp bad response: HTTP {response.status_code}", reason=Reason.ERP_BAD_RESPONSE
    )


def bad_response(response: httpx.Response) -> UpstreamUnavailableError:
    return UpstreamUnavailableError(
        f"erp bad response: HTTP {response.status_code}", reason=Reason.ERP_BAD_RESPONSE
    )
