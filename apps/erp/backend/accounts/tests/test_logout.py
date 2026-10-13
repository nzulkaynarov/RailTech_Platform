"""Token revocation / logout — POST /api/v1/auth/logout/ (was missing).

Access tokens are short-lived, but a refresh token lived 7 days with no kill
switch. Logout now blacklists it so a stolen copy can't mint new access tokens.
"""

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken


@pytest.mark.django_db
def test_logout_blacklists_the_refresh_token(user_factory):
    user = user_factory()
    refresh = RefreshToken.for_user(user)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")

    resp = client.post("/api/v1/auth/logout/", {"refresh": str(refresh)}, format="json")
    assert resp.status_code == 205

    # The blacklisted refresh token can no longer mint a new access token.
    refreshed = APIClient().post("/api/v1/auth/token/refresh/", {"refresh": str(refresh)}, format="json")
    assert refreshed.status_code == 401


@pytest.mark.django_db
def test_logout_is_idempotent_without_token(user_factory):
    user = user_factory()
    refresh = RefreshToken.for_user(user)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")
    # No `refresh` in body — still succeeds (e.g. client lost the refresh token).
    assert client.post("/api/v1/auth/logout/", {}, format="json").status_code == 205


@pytest.mark.django_db
def test_logout_all_revokes_every_user_token(user_factory):
    user = user_factory()
    first = RefreshToken.for_user(user)
    second = RefreshToken.for_user(user)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {first.access_token}")

    assert client.post("/api/v1/auth/logout/", {"all": True}, format="json").status_code == 205

    for token in (first, second):
        refreshed = APIClient().post("/api/v1/auth/token/refresh/", {"refresh": str(token)}, format="json")
        assert refreshed.status_code == 401


@pytest.mark.django_db
def test_logout_requires_authentication():
    assert APIClient().post("/api/v1/auth/logout/", {}, format="json").status_code == 401
