"""Django admin ERP под путём на домене Платформы (OPS-CONSOLE, DECISIONS 2026-11-03).

Администратор открывает панель базы ERP по адресу `https://<Платформа>/console/erp/admin/`: Caddy
пропускает туда только после проверки сессии Платформы (`forward_auth` к BFF) и проксирует путь
целиком, с префиксом. Эта обёртка ASGI ставит префикс в `root_path` запроса, и Django сам строит
ссылки, редиректы и адреса статики под ним (`get_script_prefix`), не трогая остальной ERP: запрос
без префикса (API, портал, домен ERP) идёт как раньше. Под префиксом открыты только `admin/` и
`static/` — остальное 404, даже если маршрут Caddy расширят по ошибке.

Префикс задаёт окружение `ERP_CONSOLE_PREFIX` (на проде `/console/erp`); пусто — обёртка выключена.
"""

import os

from django.http import HttpResponseNotFound

ALLOWED_UNDER_PREFIX = ("/admin", "/static/")


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
        await self.app(scope, receive, send)


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
