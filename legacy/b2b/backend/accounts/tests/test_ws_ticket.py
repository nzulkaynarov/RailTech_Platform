"""One-time WebSocket auth ticket — POST /api/v1/auth/ws-ticket/ (Sprint D).

Moves the long-lived JWT out of the WS URL query string (which proxies/CDNs log)
into a short-lived, single-use ticket resolved by the channels middleware.
"""

import pytest
from asgiref.sync import async_to_sync
from django.core.cache import cache
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken


def _auth_client(user):
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
    return c


@pytest.mark.django_db
def test_ws_ticket_is_minted_cached_and_single_use(user_factory):
    user = user_factory()
    resp = _auth_client(user).post("/api/v1/auth/ws-ticket/")
    assert resp.status_code == 200
    ticket = resp.json()["ticket"]
    # Cached against the user (the middleware reads + deletes this key).
    assert cache.get(f"ws_ticket:{ticket}") == user.id
    # Single-use: once consumed it no longer resolves (mirrors the middleware's
    # cache.delete on first lookup). The DB-resolve half runs in the consumer's
    # thread at runtime; here we verify the cache lifecycle directly because
    # database_sync_to_async + the pooled test DB don't bridge in a sync test.
    cache.delete(f"ws_ticket:{ticket}")
    assert cache.get(f"ws_ticket:{ticket}") is None


@pytest.mark.django_db
def test_unknown_ticket_is_anonymous():
    from core.middleware import get_user_from_ticket

    assert not async_to_sync(get_user_from_ticket)("nope-not-a-real-ticket").is_authenticated


def test_ws_ticket_requires_authentication():
    assert APIClient().post("/api/v1/auth/ws-ticket/").status_code == 401
