"""Клиент EDS (`eds-api`): обмен токена сотрудника CRM на токен доступа EDS.

Контракт — `packages/contracts/openapi/eds.yaml`; вход — `docs/architecture/sso-token.md`, «Токен
сотрудника для EDS»: CRM `POST /api/v1/auth/sso/token {"aud": "eds"}` → EDS `POST
/api/v1/auth/sso/exchange` → токен доступа EDS на 15 минут, без refresh (истёк — BFF обменивает
новый токен CRM). Внешнего маршрута у EDS нет: только сеть compose. Health — `/health`.
"""

import httpx

from app.clients.base import BackendClient


class EdsClient(BackendClient):
    def __init__(self, base_url: str) -> None:
        super().__init__("eds", base_url, "/health")

    async def sso_exchange(self, sso_token: str) -> httpx.Response:
        return await self.send("POST", "/api/v1/auth/sso/exchange", json={"token": sso_token})
