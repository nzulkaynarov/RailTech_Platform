"""Клиент ERP для сотрудников (FIX-11, M3-CRM-06): провижининг и отзыв сессий.

`POST /api/integration/v1/users/provision` (идемпотентно по `crm_user_id`) и
`DELETE /api/integration/v1/users/{crm_user_id}/sessions` — CONTRACTS §2, `erp-integration.yaml`.
Адрес и сервисный токен — те же, что у передачи клиента (коннектор «ERP» в «Подключениях»).
Ошибки — доменные исключения: временные (`UpstreamUnavailableError`) задача повторяет, постоянные
(`ConflictError`, `ValidationFailedError`) — нет; пользователю они не показываются, их видит админ в
центре внешних сервисов (ADR-0024). Значения секретов не логируются.
"""

import uuid
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from app.config import Settings
from app.domain.erp_connector import INTEGRATION_PREFIX, base_url_problem
from app.domain.errors import (
    ConflictError,
    Reason,
    UpstreamUnavailableError,
    ValidationFailedError,
)
from app.integrations.erp import ErpConnection, resolve_connection
from app.security.secrets_store import SecretsStore
from app.services.settings import SettingsService


@dataclass(frozen=True, slots=True)
class ProvisionPayload:
    crm_user_id: int
    email: str
    name: str
    role: str
    permissions: tuple[str, ...]
    is_active: bool = True

    def as_json(self) -> dict[str, Any]:
        return {
            "crm_user_id": self.crm_user_id,
            "email": self.email,
            "name": self.name,
            "role": self.role,
            "permissions": list(self.permissions),
            "is_active": self.is_active,
        }


class ErpUsersClient(Protocol):
    async def provision_user(self, payload: ProvisionPayload) -> int:
        """Создать или обновить сотрудника в ERP; возвращает `erp_user_id`."""
        ...

    async def revoke_sessions(self, crm_user_id: int) -> bool:
        """Отозвать все сессии; `False` — в ERP такого сотрудника нет (отзывать нечего)."""
        ...


class HttpxErpUsersClient:
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

    async def provision_user(self, payload: ProvisionPayload) -> int:
        response = await self._send(
            "POST",
            "/users/provision",
            json=payload.as_json(),
            extra_headers={"Idempotency-Key": str(uuid.uuid4())},
        )
        if response.status_code == 409:
            raise ConflictError(
                f"erp refused the user: {response.text[:200]}", reason=Reason.ERP_EMAIL_CONFLICT
            )
        if response.status_code in (400, 422):
            raise ValidationFailedError(
                f"erp validation error: {response.text[:300]}", reason=Reason.ERP_BAD_RESPONSE
            )
        if response.status_code not in (200, 201):
            raise _bad_response(response)
        try:
            return int(response.json()["erp_user_id"])
        except (ValueError, KeyError, TypeError) as exc:
            raise UpstreamUnavailableError(
                f"bad json from erp: {type(exc).__name__}", reason=Reason.ERP_BAD_RESPONSE
            ) from exc

    async def revoke_sessions(self, crm_user_id: int) -> bool:
        response = await self._send("DELETE", f"/users/{int(crm_user_id)}/sessions")
        if response.status_code == 404:
            return False
        if response.status_code != 204:
            raise _bad_response(response)
        return True

    async def _connection(self) -> ErpConnection:
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
        if response.status_code in (401, 403):
            raise UpstreamUnavailableError(
                f"HTTP {response.status_code}", reason=Reason.ERP_UNAUTHORIZED
            )
        return response


def _bad_response(response: httpx.Response) -> UpstreamUnavailableError:
    return UpstreamUnavailableError(
        f"erp bad response: HTTP {response.status_code}", reason=Reason.ERP_BAD_RESPONSE
    )
