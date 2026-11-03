"""Django admin ERP под путём на домене Платформы (OPS-CONSOLE, DECISIONS 2026-11-03).

Администратор открывает панель базы ERP по адресу `https://<Платформа>/console/erp/admin/`: Caddy
пропускает туда только после проверки сессии Платформы (`forward_auth` к BFF) и проксирует путь
целиком, с префиксом. Эта обёртка ASGI ставит префикс в `root_path` запроса, и Django сам строит
ссылки, редиректы и адреса статики под ним (`get_script_prefix`), не трогая остальной ERP: запрос
без префикса (API, портал, домен ERP) идёт как раньше. Под префиксом открыты только `admin/` и
`static/` — остальное 404, даже если маршрут Caddy расширят по ошибке.

Cookie консоли (сессия и CSRF Django admin) живут на общем домене с Платформой, поэтому каждый `Set-Cookie` ответа под
префиксом получает `Path=<префикс>` вместо `Path=/`: SPA Платформы их не видит и не шлёт, а удаление при выходе
(тот же `Set-Cookie`) бьёт в тот же путь. Здесь, а не настройкой `SESSION_COOKIE_PATH`: настройка общая для API и
портала ERP без префикса, а слой ASGI знает префикс запроса и ловит любую cookie (сессия, CSRF, тема Unfold).

Префикс задаёт окружение `ERP_CONSOLE_PREFIX` (на проде `/console/erp`); пусто — обёртка выключена.
"""

import os
import re

from django.http import HttpResponseNotFound

ALLOWED_UNDER_PREFIX = ("/admin", "/static/")
_ROOT_PATH_ATTR = re.compile(rb"(;\s*path=)/(?=\s*;|\s*$)", re.IGNORECASE)


def scope_cookie_path(value: bytes, prefix: str) -> bytes:
    """`Set-Cookie: …; Path=/` -> `Path=<префикс>`; другой путь не трогается."""
    return _ROOT_PATH_ATTR.sub(lambda m: m.group(1) + prefix.encode(), value)


def console_prefix() -> str:
    raw = os.environ.get("ERP_CONSOLE_PREFIX", "").strip().rstrip("/")
    if raw and not raw.startswith("/"):
        raise ValueError("ERP_CONSOLE_PREFIX — путь от корня, например /console/erp")
    return raw


class ConsolePrefixMount:
    """ASGI: запрос под префиксом получает `root_path` = префикс; путь не меняется (Django снимет его сам)."""

    def __init__(self, app, prefix: str):
        self.app = app
        self.prefix = prefix

    async def __call__(self, scope, receive, send):
        if self.prefix and scope["type"] == "http":
            path = scope.get("path", "")
            if path == self.prefix or path.startswith(self.prefix + "/"):
                rest = path[len(self.prefix) :]
                if not rest.startswith(ALLOWED_UNDER_PREFIX):
                    await _not_found(send)
                    return
                scope = {**scope, "root_path": self.prefix}
                await self.app(scope, receive, self._scoped_cookies(send))
                return
        await self.app(scope, receive, send)

    def _scoped_cookies(self, send):
        async def wrapped(message):
            if message["type"] == "http.response.start":
                headers = [
                    (name, scope_cookie_path(value, self.prefix) if name.lower() == b"set-cookie" else value)
                    for name, value in message.get("headers", [])
                ]
                message = {**message, "headers": headers}
            await send(message)

        return wrapped


async def _not_found(send):
    response = HttpResponseNotFound()
    await send(
        {
            "type": "http.response.start",
            "status": response.status_code,
            "headers": [(b"content-type", b"text/plain; charset=utf-8"), (b"content-length", b"0")],
        }
    )
    await send({"type": "http.response.body", "body": b""})
