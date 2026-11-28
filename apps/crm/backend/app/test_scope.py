"""ТЕСТ-2: «Показывать тестовые» на стороне CRM — один запрос, одно значение.

ТЕСТ-1 прячет тестовые компании из рабочих выборок без параметра. Сотрудник с включённым
переключателем получает от BFF `?test=all` на каждый запрос чтения; middleware кладёт признак в
контекст запроса, и предикаты рабочего списка (`lead_visibility.working`, общий список сделок,
запросы клиентов, сводка сделок) пропускают тестовые компании. Решает, кому добавлять параметр,
BFF по профилю (`users.show_test`); наружу CRM не публикуется (только за BFF и Caddy).
"""

from contextvars import ContextVar
from urllib.parse import parse_qs

from starlette.types import ASGIApp, Receive, Scope, Send

_show_all: ContextVar[bool] = ContextVar("show_all_test_companies", default=False)


def show_all() -> bool:
    """Запрос пришёл с `?test=all`: тестовые компании входят в рабочие выборки."""
    return _show_all.get()


class TestScopeMiddleware:
    """Читает `?test=all` из строки запроса и держит его на время запроса."""

    __test__ = False  # не тест-класс для pytest

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        query = parse_qs(scope.get("query_string", b"").decode("latin-1"))
        token = _show_all.set("all" in query.get("test", []))
        try:
            await self.app(scope, receive, send)
        finally:
            _show_all.reset(token)
