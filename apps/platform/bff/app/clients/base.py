"""Клиент бэкенда (CRM или ERP): таймаут 3 с, X-Request-Id пробрасывается из текущего запроса.

Вызовы идут от имени сотрудника (его токен), сервисных токенов у BFF нет (ADR-0011): токен
передаётся в каждый вызов, клиент общий на всех сотрудников и ничего о них не помнит — в том числе
cookie: ответы CRM и ERP ставят refresh-cookie, но cookie-jar клиента их не хранит (иначе токен
одного сотрудника ушёл бы в запросы другого). BFF читает `Set-Cookie` сам и держит токен в сессии.
"""

from http.cookiejar import CookieJar
from http.cookies import CookieError, SimpleCookie
from typing import Any, Literal

import httpx

from app.request_id import HEADER, request_id_var

TIMEOUT_SECONDS = 3.0

Backend = Literal["crm", "erp"]


class _NoStoreJar(CookieJar):
    """Cookie-jar, который ничего не запоминает."""

    def extract_cookies(self, response: Any, request: Any) -> None:
        return None


class BackendUnavailableError(Exception):
    """Бэкенд не ответил (сеть, таймаут) или ответил 5xx: для сотрудника это «недоступен»."""

    def __init__(self, source: Backend, reason: str, *, status: int | None = None) -> None:
        super().__init__(f"{source}: {reason}")
        self.source = source
        self.reason = reason
        self.status = status


async def _forward_request_id(request: httpx.Request) -> None:
    request_id = request_id_var.get()
    if request_id:
        request.headers[HEADER] = request_id


def cookie_value(response: httpx.Response, name: str) -> str | None:
    """Значение cookie `name` из `Set-Cookie`; удаление cookie (пусто, Max-Age=0) — `None`."""
    for header in response.headers.get_list("set-cookie"):
        jar: SimpleCookie = SimpleCookie()
        try:
            jar.load(header)
        except CookieError:
            continue
        morsel = jar.get(name)
        if morsel is None:
            continue
        if not morsel.value or morsel["max-age"] == "0":
            return None
        return morsel.value
    return None


class BackendClient:
    def __init__(
        self,
        name: Backend,
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
        self.http.cookies.jar = _NoStoreJar()

    async def is_healthy(self) -> bool:
        """Бэкенд жив, если его health отвечает 200 за таймаут; любая ошибка — «не жив»."""
        try:
            response = await self.http.get(self.health_path)
        except httpx.HTTPError:
            return False
        return response.status_code == httpx.codes.OK

    async def send(
        self,
        method: str,
        path: str,
        *,
        access: str | None = None,
        cookies: dict[str, str] | None = None,
        json: Any = None,
        params: dict[str, Any] | None = None,
    ) -> httpx.Response:
        """Вызов бэкенда от имени сотрудника. 2xx и 4xx возвращаются как есть (решает вызывающий),
        сеть, таймаут и 5xx — `BackendUnavailableError`."""
        headers: dict[str, str] = {}
        if access:
            headers["Authorization"] = f"Bearer {access}"
        if cookies:
            headers["Cookie"] = "; ".join(f"{k}={v}" for k, v in cookies.items())
        try:
            response = await self.http.request(
                method, path, headers=headers, json=json, params=params
            )
        except httpx.HTTPError as exc:
            raise BackendUnavailableError(self.name, type(exc).__name__) from exc
        if response.status_code >= 500:
            raise BackendUnavailableError(
                self.name, f"HTTP {response.status_code}", status=response.status_code
            )
        return response

    async def aclose(self) -> None:
        await self.http.aclose()
