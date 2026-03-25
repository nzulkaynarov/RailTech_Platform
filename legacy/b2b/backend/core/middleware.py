"""
JWT Auth Middleware for Django Channels WebSockets.

Standard DRF JWT (simplejwt) only works with HTTP requests.
This middleware reads the token from the query string (`?token=...`)
and populates scope['user'] for use inside AsyncWebsocketConsumers.
"""

from urllib.parse import parse_qs
from channels.middleware import BaseMiddleware
from channels.db import database_sync_to_async


@database_sync_to_async
def get_user_from_token(token_key):
    try:
        from rest_framework_simplejwt.tokens import AccessToken
        from accounts.models import CustomUser
        from django.contrib.auth.models import AnonymousUser

        access_token = AccessToken(token_key)
        user_id = access_token['user_id']
        return CustomUser.objects.get(id=user_id)
    except Exception:
        return AnonymousUser()


class JwtAuthMiddleware(BaseMiddleware):
    """
    Reads ?token=<JWT> from the WebSocket URL query string
    and authenticates the user before the consumer starts.
    """

    async def __call__(self, scope, receive, send):
        query_string = scope.get('query_string', b'').decode()
        params = parse_qs(query_string)
        token_list = params.get('token', [None])
        token = token_list[0]

        if token:
            scope['user'] = await get_user_from_token(token)
        else:
            from django.contrib.auth.models import AnonymousUser
            scope['user'] = AnonymousUser()

        return await super().__call__(scope, receive, send)


def JwtAuthMiddlewareStack(inner):
    return JwtAuthMiddleware(inner)
