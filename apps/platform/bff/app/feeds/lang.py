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
    """Язык из `Accept-Language` с учётом весов (`q`): `uz`, `uz-*`, `en`, `en-*`, `ru`, `ru-*`.

    Побеждает поддерживаемый язык с наибольшим весом (при равенстве — раньше в списке);
    `q=0` — «не хочу»; нет или чужие языки — русский."""
    best, best_q = "ru", 0.0
    for part in (header or "").split(","):
        tag, *params = (piece.strip() for piece in part.split(";"))
        primary = tag.lower().split("-")[0]
        if primary not in LANGUAGES:
            continue
        weight = 1.0
        for param in params:
            if param.lower().startswith("q="):
                try:
                    weight = float(param[2:])
                except ValueError:
                    weight = 0.0
        if weight > best_q:
            best, best_q = primary, weight
    return best


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
