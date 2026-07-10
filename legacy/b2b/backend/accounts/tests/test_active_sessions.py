"""Active-session management — /auth/sessions[/revoke-all].

Pinned behaviour (2026-07-10 review of the externally-contributed endpoints):
    * a "session" is a live (non-blacklisted, unexpired) refresh token;
    * `is_current` marks the row matching the browser's HttpOnly refresh cookie;
    * revoke-all SPARES the current session — "log out everywhere else" must not
      also log out the browser that clicked it (the original blacklisted
      everything, silently killing the caller's own session);
    * the endpoints MUST live under REFRESH_COOKIE_PATH: the refresh cookie is
      path-scoped, so a real browser only sends it below /api/v1/auth/. The
      first version sat at /accounts/users/me/sessions where the cookie never
      arrived — is_current was always false and revoke-all nuked the caller's
      own session. APIClient ignores cookie paths, hence the URL invariant test.
"""

import pytest
from django.conf import settings as django_settings
from django.core.cache import cache
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

LOCMEM = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}

PASSWORD = "testpass123"


@pytest.fixture(autouse=True)
def _isolated_cache(settings):
    settings.CACHES = LOCMEM
    cache.clear()
    yield
    cache.clear()


def _login_client(user):
    """Client logged in through the real cookie flow (refresh in client.cookies)."""
    client = APIClient()
    resp = client.post("/api/v1/auth/token/", {"email": user.email, "password": PASSWORD}, format="json")
    assert resp.status_code == 200
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['access']}")
    return client


@pytest.mark.django_db
def test_sessions_list_marks_the_current_browser(user_factory):
    user = user_factory()
    client = _login_client(user)
    RefreshToken.for_user(user)  # a second, unrelated session

    resp = client.get("/api/v1/auth/sessions/")
    assert resp.status_code == 200
    sessions = resp.data["sessions"]
    assert len(sessions) == 2
    assert sum(1 for s in sessions if s["is_current"]) == 1
    assert all("jti" not in s for s in sessions)  # token internals stay server-side


@pytest.mark.django_db
def test_revoke_all_spares_the_current_session(user_factory):
    user = user_factory()
    client = _login_client(user)
    other = RefreshToken.for_user(user)

    resp = client.post("/api/v1/auth/sessions/revoke-all/")
    assert resp.status_code == 200
    assert resp.data["revoked"] == 1

    remaining = client.get("/api/v1/auth/sessions/").data["sessions"]
    assert len(remaining) == 1 and remaining[0]["is_current"]

    # The other device's refresh token is dead...
    dead = APIClient().post("/api/v1/auth/token/refresh/", {"refresh": str(other)}, format="json")
    assert dead.status_code == 401
    # ...while THIS browser's cookie still refreshes fine (checked last — rotation
    # blacklists the old cookie token, which would skew the assertions above).
    own = client.cookies.get(django_settings.REFRESH_COOKIE_NAME).value
    alive = APIClient().post("/api/v1/auth/token/refresh/", {"refresh": own}, format="json")
    assert alive.status_code == 200


@pytest.mark.django_db
def test_sessions_require_authentication():
    assert APIClient().get("/api/v1/auth/sessions/").status_code == 401
    assert APIClient().post("/api/v1/auth/sessions/revoke-all/").status_code == 401


def test_session_endpoints_live_under_the_refresh_cookie_path():
    """URL invariant that would have caught the original bug: the browser only
    sends the path-scoped refresh cookie below REFRESH_COOKIE_PATH, so both
    session endpoints must resolve under it (APIClient can't detect this —
    it posts cookies regardless of their path)."""
    for name in ("auth-sessions", "auth-sessions-revoke-all"):
        url = reverse(name)
        assert url.startswith(django_settings.REFRESH_COOKIE_PATH), (name, url)
