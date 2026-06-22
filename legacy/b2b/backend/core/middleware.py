"""
JWT Auth Middleware for Django Channels WebSockets.

Standard DRF JWT (simplejwt) only works with HTTP requests.
This middleware reads the token from the query string (`?token=...`)
and populates scope['user'] for use inside AsyncWebsocketConsumers.
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

    key = f"ws_ticket:{ticket}"
    user_id = cache.get(key)
    if user_id is None:
        return AnonymousUser()
    cache.delete(key)  # consume — single use
    try:
        return CustomUser.objects.get(id=user_id)
    except CustomUser.DoesNotExist:
        return AnonymousUser()


@database_sync_to_async
def get_user_from_token(token_key):
    from django.contrib.auth.models import AnonymousUser
    from rest_framework_simplejwt.exceptions import InvalidToken, TokenError

    from accounts.models import CustomUser

    try:
        from rest_framework_simplejwt.tokens import AccessToken

        access_token = AccessToken(token_key)
        user_id = access_token["user_id"]
        return CustomUser.objects.get(id=user_id)
    except (InvalidToken, TokenError, KeyError, CustomUser.DoesNotExist):
        # Expired/invalid token or unknown user → anonymous, expected path.
        return AnonymousUser()
    except Exception:
        # Unexpected failure (e.g. DB error): log it instead of silently
        # masking it as "no token", then still fail closed to anonymous.
        logger.exception("Unexpected error authenticating WebSocket token")
        return AnonymousUser()


class JwtAuthMiddleware(BaseMiddleware):
    """
    Authenticates a WebSocket connection before the consumer starts.

    Prefers a one-time `?ticket=` (minted by /auth/ws-ticket/) so the long-lived
    JWT no longer travels in the URL. Falls back to the legacy `?token=<JWT>` for
    backward compatibility during the SPA rollout.
    """

    async def __call__(self, scope, receive, send):
        from django.contrib.auth.models import AnonymousUser

        query_string = scope.get("query_string", b"").decode()
        params = parse_qs(query_string)
        ticket = params.get("ticket", [None])[0]
        token = params.get("token", [None])[0]

        if ticket:
            scope["user"] = await get_user_from_ticket(ticket)
        elif token:
            scope["user"] = await get_user_from_token(token)
        else:
            scope["user"] = AnonymousUser()

        return await super().__call__(scope, receive, send)


def JwtAuthMiddlewareStack(inner):
    return JwtAuthMiddleware(inner)
