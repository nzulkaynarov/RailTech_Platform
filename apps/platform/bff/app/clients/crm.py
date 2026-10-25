"""Клиент CRM (`crm-api`): вход, обновление и выход сотрудника, профиль, SSO-токен для ERP.

Контракт CRM — `packages/contracts/openapi/crm.yaml` (его генерирует CRM).
Тела ответов разбираются сгенерированными моделями `crm_models` (`make crm-models` платформы).
Health CRM — `/health` в корне.
"""

from dataclasses import dataclass

import httpx

from app.clients.base import (
    CRM_TIMEOUT_SECONDS,
    BackendClient,
    BackendUnavailableError,
    cookie_value,
)
from app.clients.crm_models import TokenResponse

REFRESH_COOKIE = "rt_refresh"


@dataclass(frozen=True)
class CrmTokens:
    """Ответ входа и обновления CRM: access (в теле), refresh (cookie), срок access в секундах."""

    access: str
    expires_in: int
    refresh: str | None
    must_change_password: bool


class CrmClient(BackendClient):
    def __init__(self, base_url: str, timeout: float = CRM_TIMEOUT_SECONDS) -> None:
        super().__init__("crm", base_url, "/health", timeout=timeout)

    @staticmethod
    def tokens(response: httpx.Response) -> CrmTokens:
        body = TokenResponse.model_validate(response.json())
        return CrmTokens(
            access=body.access_token,
            expires_in=body.expires_in,
            refresh=cookie_value(response, REFRESH_COOKIE),
            must_change_password=body.must_change_password,
        )

    async def login(
        self, email: str, password: str, client_ip: str | None = None
    ) -> httpx.Response:
        """Вход. `client_ip` — адрес сотрудника: CRM видит только BFF, а аудит входа ведёт по
        `X-Forwarded-For` (uvicorn `proxy_headers`, `FORWARDED_ALLOW_IPS` у crm-api)."""
        return await self.send(
            "POST",
            "/api/v1/auth/login",
            json={"email": email, "password": password},
            headers={"X-Forwarded-For": client_ip} if client_ip else None,
        )

    async def refresh(self, refresh_token: str) -> httpx.Response:
        return await self.send(
            "POST", "/api/v1/auth/refresh", cookies={REFRESH_COOKIE: refresh_token}
        )

    async def logout(self, refresh_token: str) -> None:
        """Погасить семью refresh-токенов CRM. Ошибки не пробрасываются: выход идемпотентен."""
        try:
            await self.send("POST", "/api/v1/auth/logout", cookies={REFRESH_COOKIE: refresh_token})
        except BackendUnavailableError:
            return

    async def me(self, access: str) -> httpx.Response:
        return await self.send("GET", "/api/v1/me", access=access)

    async def sso_token(self, access: str) -> httpx.Response:
        return await self.send("POST", "/api/v1/auth/sso/token", access=access)

    async def change_password(self, access: str, current: str, new: str) -> httpx.Response:
        return await self.send(
            "POST",
            "/api/v1/auth/change-password",
            access=access,
            json={"current_password": current, "new_password": new},
        )
