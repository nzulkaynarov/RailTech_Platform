"""2FA (TOTP) — setup/verify/disable + the two-step login flow.

Hardening pinned here (2026-07-10 review of the externally-contributed 2FA):
    * the password step never leaks tokens for a 2FA account (the minted pair is
      voided — its refresh is blacklisted);
    * /auth/login/2fa/ returns the refresh token ONLY as the HttpOnly cookie;
    * wrong codes charge the SEC-06 per-account lockout (distributed brute-force
      on the 6-digit code is not free);
    * error responses carry CODES ({"detail": "2FA_INVALID_CODE"}), not prose.
"""

import pyotp
import pytest
from django.conf import settings as django_settings
from django.core.cache import cache
from rest_framework.test import APIClient
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken

# Isolated in-memory cache so throttle/lockout history never leaks across tests.
LOCMEM = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}

PASSWORD = "testpass123"


@pytest.fixture(autouse=True)
def _isolated_cache(settings):
    settings.CACHES = LOCMEM
    cache.clear()
    yield
    cache.clear()


def _auth_client(user):
    from rest_framework_simplejwt.tokens import RefreshToken

    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
    return client


def _enable_2fa(user):
    user.totp_secret = pyotp.random_base32()
    user.is_2fa_enabled = True
    user.save(update_fields=["totp_secret", "is_2fa_enabled"])
    return user.totp_secret


def _login(client, email, password=PASSWORD, **extra):
    return client.post("/api/v1/auth/token/", {"email": email, "password": password}, format="json", **extra)


@pytest.mark.django_db
class TestTotpSetup:
    def test_setup_then_verify_enables_2fa(self, user_factory):
        user = user_factory()
        client = _auth_client(user)

        setup = client.post("/api/v1/auth/2fa/setup/")
        assert setup.status_code == 200
        secret = setup.data["secret"]
        assert "otpauth://" in setup.data["uri"]
        user.refresh_from_db()
        assert not user.is_2fa_enabled  # nothing persists until the code is confirmed

        code = pyotp.TOTP(secret).now()
        verify = client.post("/api/v1/auth/2fa/verify/", {"secret": secret, "code": code}, format="json")
        assert verify.status_code == 200
        user.refresh_from_db()
        assert user.is_2fa_enabled and user.totp_secret == secret

    def test_verify_rejects_wrong_code(self, user_factory):
        user = user_factory()
        client = _auth_client(user)
        secret = pyotp.random_base32()

        resp = client.post("/api/v1/auth/2fa/verify/", {"secret": secret, "code": "000000"}, format="json")
        assert resp.status_code == 400
        assert resp.data["detail"] == "2FA_INVALID_CODE"
        user.refresh_from_db()
        assert not user.is_2fa_enabled

    def test_verify_requires_secret_and_code(self, user_factory):
        client = _auth_client(user_factory())
        resp = client.post("/api/v1/auth/2fa/verify/", {}, format="json")
        assert resp.status_code == 400
        assert resp.data["detail"] == "2FA_CODE_REQUIRED"

    def test_setup_blocked_when_already_enabled(self, user_factory):
        user = user_factory()
        _enable_2fa(user)
        resp = _auth_client(user).post("/api/v1/auth/2fa/setup/")
        assert resp.status_code == 400
        assert resp.data["detail"] == "2FA_ALREADY_ENABLED"

    def test_disable_requires_valid_code(self, user_factory):
        user = user_factory()
        secret = _enable_2fa(user)
        client = _auth_client(user)

        bad = client.post("/api/v1/auth/2fa/disable/", {"code": "000000"}, format="json")
        assert bad.status_code == 400
        assert bad.data["detail"] == "2FA_INVALID_CODE"

        good = client.post("/api/v1/auth/2fa/disable/", {"code": pyotp.TOTP(secret).now()}, format="json")
        assert good.status_code == 200
        user.refresh_from_db()
        assert not user.is_2fa_enabled and user.totp_secret is None


@pytest.mark.django_db
class TestTwoStepLogin:
    def test_password_step_returns_ticket_and_voids_the_minted_pair(self, user_factory):
        user = user_factory()
        _enable_2fa(user)

        resp = _login(APIClient(), user.email)
        assert resp.status_code == 200
        assert resp.data.get("2fa_required") is True
        assert resp.data.get("temp_token")
        assert "access" not in resp.data and "refresh" not in resp.data
        assert django_settings.REFRESH_COOKIE_NAME not in resp.cookies
        # The pair simplejwt minted during password verification must be dead.
        assert BlacklistedToken.objects.filter(token__user=user).count() == 1

    def test_code_step_sets_cookie_and_never_returns_refresh_in_body(self, user_factory):
        user = user_factory()
        secret = _enable_2fa(user)
        client = APIClient()
        ticket = _login(client, user.email).data["temp_token"]

        resp = client.post(
            "/api/v1/auth/login/2fa/",
            {"temp_token": ticket, "code": pyotp.TOTP(secret).now()},
            format="json",
        )
        assert resp.status_code == 200
        assert resp.data.get("access")
        assert "refresh" not in resp.data
        assert resp.cookies[django_settings.REFRESH_COOKIE_NAME]["httponly"]

    def test_wrong_code_is_rejected_with_a_code(self, user_factory):
        user = user_factory()
        _enable_2fa(user)
        client = APIClient()
        ticket = _login(client, user.email).data["temp_token"]

        resp = client.post("/api/v1/auth/login/2fa/", {"temp_token": ticket, "code": "000000"}, format="json")
        assert resp.status_code == 400
        assert resp.data["detail"] == "2FA_INVALID_CODE"

    def test_garbage_ticket_is_rejected(self):
        resp = APIClient().post(
            "/api/v1/auth/login/2fa/", {"temp_token": "not-a-ticket", "code": "123456"}, format="json"
        )
        assert resp.status_code == 400
        assert resp.data["detail"] == "2FA_TICKET_INVALID"

    def test_wrong_password_behaves_like_any_failed_login(self, user_factory):
        user = user_factory()
        _enable_2fa(user)
        resp = _login(APIClient(), user.email, password="wrong-password")
        assert resp.status_code == 401
        assert "2fa_required" not in (resp.data or {})

    def test_distributed_code_bruteforce_trips_the_account_lockout(self, user_factory, settings):
        settings.LOGIN_LOCKOUT_DISTINCT_IPS = 2
        user = user_factory()
        _enable_2fa(user)
        client = APIClient()
        ticket = _login(client, user.email).data["temp_token"]

        for ip in ("10.9.9.1", "10.9.9.2"):
            resp = client.post(
                "/api/v1/auth/login/2fa/",
                {"temp_token": ticket, "code": "000000"},
                format="json",
                REMOTE_ADDR=ip,
            )
            assert resp.status_code == 400

        locked = client.post(
            "/api/v1/auth/login/2fa/",
            {"temp_token": ticket, "code": "000000"},
            format="json",
            REMOTE_ADDR="10.9.9.3",
        )
        assert locked.status_code == 429
        assert locked.data["detail"] == "TOO_MANY_LOGIN_ATTEMPTS"

    def test_me_exposes_the_2fa_flag(self, user_factory):
        user = user_factory()
        _enable_2fa(user)
        resp = _auth_client(user).get("/api/v1/accounts/users/me/")
        assert resp.status_code == 200
        assert resp.data["is_2fa_enabled"] is True
