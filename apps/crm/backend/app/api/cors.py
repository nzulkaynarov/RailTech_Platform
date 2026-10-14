"""CORS только для публичной формы «Запрос» (M3-CRM-05).

CRM-фронт живёт на том же origin, что и API (Caddy), поэтому глобальный CORS не нужен и опасен.
Форму вызывает страница входа Cabinet (`cabinet.railtech.uz` / `cabinet.localhost`), поэтому
Starlette `CORSMiddleware` с origin из `CABINET_ORIGIN` навешивается только на пути
`/api/v1/leads/web*` — остальные запросы проходят как раньше (без CORS-заголовков).
"""

from collections.abc import Sequence
from typing import Final

from starlette.middleware.cors import CORSMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send

WEB_LEAD_PREFIX: Final = "/api/v1/leads/web"


class WebLeadCorsMiddleware:
    def __init__(self, app: ASGIApp, *, origins: Sequence[str]) -> None:
        self._app = app
        self._cors = CORSMiddleware(
            app,
            allow_origins=list(origins),
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["Content-Type", "X-Request-ID"],
            allow_credentials=False,
            max_age=600,
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and str(scope.get("path", "")).startswith(WEB_LEAD_PREFIX):
            await self._cors(scope, receive, send)
            return
        await self._app(scope, receive, send)
