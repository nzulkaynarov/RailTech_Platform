"""SEC-06 — per-account login lockout (accounts/services/login_guard).

Uses an isolated LocMemCache per test so the tests neither touch the shared dev
Redis nor collide with the per-IP `login` throttle (which lives in the same cache).
"""

import pytest
from django.core.cache import cache
from django.urls import reverse
from rest_framework.test import APIClient

from accounts.models import CustomUser
from accounts.services import login_guard

LOCMEM = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "sec06-login-guard",
    }
}


@pytest.fixture
def isolated_cache(settings):
    """Swap in a private in-memory cache and empty it around each test."""
    settings.CACHES = LOCMEM
    cache.clear()
    yield
    cache.clear()


@pytest.mark.usefixtures("isolated_cache")
class TestLoginGuardUnit:
    """Counter / lock / reset semantics — no DB, no HTTP."""

    def test_below_threshold_not_locked(self):
        for _ in range(9):  # default threshold is 10
            login_guard.record_failure("victim@example.com")
        assert login_guard.is_locked("victim@example.com") is False

    def test_reaches_threshold_locks(self):
        for _ in range(10):
            login_guard.record_failure("victim@example.com")
        assert login_guard.is_locked("victim@example.com") is True

    def test_reset_clears_lock(self):
        for _ in range(10):
            login_guard.record_failure("victim@example.com")
        assert login_guard.is_locked("victim@example.com") is True
        login_guard.reset("victim@example.com")
        assert login_guard.is_locked("victim@example.com") is False

    def test_empty_email_never_locks(self):
        for _ in range(20):
            login_guard.record_failure("")
        assert login_guard.is_locked("") is False

    def test_identifier_is_case_and_whitespace_insensitive(self):
        for _ in range(10):
            login_guard.record_failure("Victim@Example.com")
        # A trimmed/lowercased variant normalizes to the same locked identity.
        assert login_guard.is_locked("  victim@example.com  ") is True

    def test_nonexistent_email_locks_identically(self):
        # No account enumeration — a bogus address locks the same way a real one does.
        for _ in range(10):
            login_guard.record_failure("no-such-user@nowhere.tld")
        assert login_guard.is_locked("no-such-user@nowhere.tld") is True


@pytest.mark.django_db
@pytest.mark.usefixtures("isolated_cache")
class TestLoginLockoutEndpoint:
    """End-to-end through POST /api/v1/auth/token/ (threshold lowered to 3)."""

    @pytest.fixture(autouse=True)
    def _low_threshold(self, settings):
        settings.LOGIN_LOCKOUT_THRESHOLD = 3

    def _make_user(self):
        return CustomUser.objects.create_user(
            email="lockme@railtech.test",
            username="lockme@railtech.test",
            password="Right-pw-123!",
        )

    def test_failures_lock_then_block_even_correct_password(self):
        user = self._make_user()
        client = APIClient()
        url = reverse("token_obtain_pair")

        for _ in range(3):  # == threshold
            resp = client.post(url, {"email": user.email, "password": "wrong"}, format="json")
            assert resp.status_code == 401

        # Locked: the CORRECT password is now refused too, with a generic 429.
        resp = client.post(url, {"email": user.email, "password": "Right-pw-123!"}, format="json")
        assert resp.status_code == 429
        assert resp["Retry-After"]
        assert resp.data["detail"] == "TOO_MANY_LOGIN_ATTEMPTS"

    def test_successful_login_resets_counter(self):
        user = self._make_user()
        client = APIClient()
        url = reverse("token_obtain_pair")

        for _ in range(2):  # below threshold
            client.post(url, {"email": user.email, "password": "wrong"}, format="json")

        resp = client.post(url, {"email": user.email, "password": "Right-pw-123!"}, format="json")
        assert resp.status_code == 200
        assert login_guard.is_locked(user.email) is False

        # Counter was cleared — a single later failure does not immediately re-lock.
        client.post(url, {"email": user.email, "password": "wrong"}, format="json")
        assert login_guard.is_locked(user.email) is False
