"""Клиент бэкенда (CRM или ERP): таймаут 3 с, X-Request-Id пробрасывается из текущего запроса.

Вызовы идут от имени сотрудника (его токен), сервисных токенов у BFF нет (ADR-0011); токены
подставляют методы фазы P1, здесь — только транспорт.
"""

import httpx

from app.request_id import HEADER, request_id_var

TIMEOUT_SECONDS = 3.0


async def _forward_request_id(request: httpx.Request) -> None:
    request_id = request_id_var.get()
    if request_id:
        request.headers[HEADER] = request_id


class BackendClient:
    def __init__(
        self,
        name: str,
        base_url: str,
        health_path: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.name = name
        self.health_path = health_path
        self.http = httpx.AsyncClient(
            base_url=base_url,
            timeout=httpx.Timeout(TIMEOUT_SECONDS),
            event_hooks={"request": [_forward_request_id]},
            transport=transport,
        )

    async def is_healthy(self) -> bool:
        """Бэкенд жив, если его health отвечает 200 за таймаут; любая ошибка — «не жив»."""
        try:
            response = await self.http.get(self.health_path)
        except httpx.HTTPError:
            return False
        return response.status_code == httpx.codes.OK

    async def aclose(self) -> None:
        await self.http.aclose()
