"""Клиент ERP (`erp-backend`): SSO-обмен, обновление и выход сотрудника.

Контракт ERP — apps/erp/backend/accounts/views/sso.py и auth.py. Health ERP — `/health/` в корне.
Refresh-токен ERP живёт в cookie с именем `REFRESH_COOKIE_NAME` ERP (по умолчанию `refresh_token`).
"""

import httpx

from app.clients.base import BackendClient, BackendUnavailableError


class ErpClient(BackendClient):
    def __init__(self, base_url: str, refresh_cookie: str = "refresh_token") -> None:
        super().__init__("erp", base_url, "/health/")
        self.refresh_cookie = refresh_cookie

    async def sso_exchange(self, sso_token: str) -> httpx.Response:
        return await self.send("POST", "/api/v1/auth/sso/exchange/", json={"token": sso_token})

    async def refresh(self, refresh_token: str) -> httpx.Response:
        return await self.send(
            "POST", "/api/v1/auth/token/refresh/", cookies={self.refresh_cookie: refresh_token}
        )

    async def logout(self, access: str, refresh_token: str) -> None:
        """Погасить refresh-токен ERP; ошибки не пробрасываются (выход идемпотентен)."""
        try:
            await self.send(
                "POST",
                "/api/v1/auth/logout/",
                access=access,
                cookies={self.refresh_cookie: refresh_token},
            )
        except BackendUnavailableError:
            return
