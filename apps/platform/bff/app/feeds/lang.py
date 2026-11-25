"""Язык текстов, которые BFF собирает сам: строки «Моей очереди», карточки, «Вы ждёте других».

Язык берётся из `Accept-Language` запроса (Платформа шлёт язык интерфейса): `ru` (по
умолчанию), `uz`, `en`. Текст строки собирает BFF из фактов источника, поэтому перевод живёт
здесь, одним вызовом `tr(ru, uz, en)` у каждой фразы, а не словарём ключей: русский вариант
остаётся рядом с кодом, который его строит. Язык лежит в `ContextVar`, чтобы не
протаскивать его через каждую функцию сборки.
"""

from contextvars import ContextVar

from starlette.datastructures import Headers
from starlette.types import ASGIApp, Receive, Scope, Send

LANGUAGES = ("ru", "uz", "en")
lang_var: ContextVar[str] = ContextVar("feed_lang", default="ru")


def parse_language(header: str | None) -> str:
    """Первый поддерживаемый язык из `Accept-Language`; нет или чужой — русский."""
    for part in (header or "").split(","):
        tag = part.split(";")[0].strip().lower()[:2]
        if tag in LANGUAGES:
            return tag
    return "ru"


def tr(ru: str, uz: str, en: str) -> str:
    """Фраза на языке запроса."""
    language = lang_var.get()
    return uz if language == "uz" else en if language == "en" else ru


class LanguageMiddleware:
    """Кладёт язык запроса в `lang_var` на время обработки."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        token = lang_var.set(parse_language(Headers(scope=scope).get("accept-language")))
        try:
            await self.app(scope, receive, send)
        finally:
            lang_var.reset(token)
