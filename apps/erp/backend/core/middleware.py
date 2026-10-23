"""
JWT Auth Middleware for Django Channels WebSockets.

Standard DRF JWT (simplejwt) only works with HTTP requests. This middleware
resolves a one-time `?ticket=` (minted by /auth/ws-ticket/) into scope['user']
for AsyncWebsocketConsumers — so the long-lived JWT never travels in the URL
(where it would land in proxy/CDN logs).
"""

import logging
from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from channels.middleware import BaseMiddleware

logger = logging.getLogger(__name__)


@database_sync_to_async
def get_user_from_ticket(ticket):
    """Resolve + consume a one-time WS ticket (minted by /auth/ws-ticket/).

    Single-use: deleted on first lookup so a leaked ticket can't be replayed.
    Returns AnonymousUser if the ticket is unknown/expired/already-used.
    """
    from django.contrib.auth.models import AnonymousUser
    from django.core.cache import cache

    from accounts.models import CustomUser
    from core.cache import CacheUnavailable, fail_closed

    key = f"ws_ticket:{ticket}"
    # S0-2: билет гасится строго и атомарно — `delete` возвращает True только тому, кто реально удалил ключ, поэтому два
    # одновременных подключения с одним билетом не пройдут оба; кэш недоступен — билет не принят (а не «пусто = можно»).
    try:
        with fail_closed():
            user_id = cache.get(key)
            if user_id is None or not cache.delete(key):  # consume — single use
                return AnonymousUser()
    except CacheUnavailable:
        return AnonymousUser()
    try:
        return CustomUser.objects.get(id=user_id)
    except CustomUser.DoesNotExist:
        return AnonymousUser()


class JwtAuthMiddleware(BaseMiddleware):
    """
    Authenticates a WebSocket connection before the consumer starts, from a
    one-time `?ticket=` (minted by /auth/ws-ticket/). The legacy `?token=<JWT>`
    fallback was removed (SEC-07): the SPA has used tickets only since rollout,
    and a long-lived JWT in the query string leaks into proxy/CDN logs.
    """

    async def __call__(self, scope, receive, send):
        from django.contrib.auth.models import AnonymousUser

        query_string = scope.get("query_string", b"").decode()
        params = parse_qs(query_string)
        ticket = params.get("ticket", [None])[0]

        scope["user"] = await get_user_from_ticket(ticket) if ticket else AnonymousUser()

        return await super().__call__(scope, receive, send)


def JwtAuthMiddlewareStack(inner):
    return JwtAuthMiddleware(inner)
