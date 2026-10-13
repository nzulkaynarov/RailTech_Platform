"""F2.1 — refresh token in an HttpOnly cookie (login / refresh / logout)."""

import pytest
from django.conf import settings
from rest_framework.test import APIClient

from accounts.models import CustomUser

COOKIE = settings.REFRESH_COOKIE_NAME


@pytest.fixture
def user(db):
    return CustomUser.objects.create_user(
        email="cookie.user@example.com", username="cookie.user@example.com", password="Secret123!", is_active=True
    )


@pytest.mark.django_db
def test_login_sets_httponly_refresh_cookie_and_no_body_refresh(user):
    client = APIClient()
    resp = client.post("/api/v1/auth/token/", {"email": user.email, "password": "Secret123!"}, format="json")
    assert resp.status_code == 200
    assert "access" in resp.data
    assert "refresh" not in resp.data  # refresh must NOT be exposed to JS
    cookie = resp.cookies.get(COOKIE)
    assert cookie is not None
    assert cookie["httponly"]
    assert cookie["path"] == settings.REFRESH_COOKIE_PATH
    assert cookie.value  # a real token


@pytest.mark.django_db
def test_refresh_reads_cookie_no_body(user):
    client = APIClient()
    client.post("/api/v1/auth/token/", {"email": user.email, "password": "Secret123!"}, format="json")
    # APIClient keeps the cookie; refresh with an EMPTY body must still work.
    resp = client.post("/api/v1/auth/token/refresh/", {}, format="json")
    assert resp.status_code == 200
    assert "access" in resp.data
    assert "refresh" not in resp.data  # rotated refresh goes back as a cookie, not body
    assert resp.cookies.get(COOKIE) is not None  # rotation re-sets the cookie


@pytest.mark.django_db
def test_refresh_without_cookie_401():
    client = APIClient()
    resp = client.post("/api/v1/auth/token/refresh/", {}, format="json")
    assert resp.status_code == 401


@pytest.mark.django_db
def test_logout_clears_cookie(user):
    client = APIClient()
    login = client.post("/api/v1/auth/token/", {"email": user.email, "password": "Secret123!"}, format="json")
    # Logout requires auth; the SPA attaches the in-memory access token via its interceptor.
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")
    resp = client.post("/api/v1/auth/logout/", {}, format="json")
    assert resp.status_code == 205
    cleared = resp.cookies.get(COOKIE)
    # delete_cookie sets an empty value with a past expiry.
    assert cleared is not None
    assert cleared.value == ""
