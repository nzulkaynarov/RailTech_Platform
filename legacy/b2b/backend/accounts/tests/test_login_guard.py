"""SEC-06 — per-account login lockout keyed on DISTINCT source IPs.

Uses an isolated LocMemCache per test so the tests neither touch the shared dev
Redis nor collide with the per-IP `login` throttle (which lives in the same cache).
"""

import time

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
    """Distinct-IP counter / lock / reset semantics — no DB, no HTTP."""

    def test_single_ip_never_locks(self):
        # The ship-blocker fix: one IP hammering (already the per-IP throttle's job)
        # must NEVER advance the account lock — otherwise it's a cheap targeted DoS.
        for _ in range(50):
            login_guard.record_failure("victim@example.com", "203.0.113.7")
        assert login_guard.is_locked("victim@example.com") is False

    def test_below_distinct_ip_threshold_not_locked(self):
        for i in range(9):  # default threshold is 10 distinct IPs
            login_guard.record_failure("victim@example.com", f"10.0.0.{i}")
        assert login_guard.is_locked("victim@example.com") is False

    def test_distinct_ips_reach_threshold_locks(self):
        for i in range(10):
            login_guard.record_failure("victim@example.com", f"10.0.0.{i}")
        assert login_guard.is_locked("victim@example.com") is True

    def test_reset_clears_lock(self):
        for i in range(10):
            login_guard.record_failure("victim@example.com", f"10.0.0.{i}")
        assert login_guard.is_locked("victim@example.com") is True
        login_guard.reset("victim@example.com")
        assert login_guard.is_locked("victim@example.com") is False

    def test_empty_email_or_ip_never_locks(self):
        for i in range(20):
            login_guard.record_failure("", f"10.0.0.{i}")
            login_guard.record_failure("victim@example.com", "")
        assert login_guard.is_locked("") is False
        assert login_guard.is_locked("victim@example.com") is False

    def test_identifier_is_case_and_whitespace_insensitive(self):
        for i in range(10):
            login_guard.record_failure("Victim@Example.com", f"10.0.0.{i}")
        # A trimmed/lowercased variant normalizes to the same locked identity.
        assert login_guard.is_locked("  victim@example.com  ") is True

    def test_nonexistent_email_locks_identically(self):
        # No account enumeration — a bogus address locks the same way a real one does.
        for i in range(10):
            login_guard.record_failure("no-such-user@nowhere.tld", f"10.0.0.{i}")
        assert login_guard.is_locked("no-such-user@nowhere.tld") is True

    def test_cooldown_auto_releases(self, settings):
        # "Temporary lock" — the lock must carry a bounded TTL and clear itself.
        settings.LOGIN_LOCKOUT_COOLDOWN = 1
        for i in range(10):
            login_guard.record_failure("victim@example.com", f"10.0.0.{i}")
        assert login_guard.is_locked("victim@example.com") is True
        time.sleep(1.2)
        assert login_guard.is_locked("victim@example.com") is False


@pytest.mark.django_db
@pytest.mark.usefixtures("isolated_cache")
class TestLoginLockoutEndpoint:
    """End-to-end through POST /api/v1/auth/token/ (distinct-IP threshold = 3)."""

    @pytest.fixture(autouse=True)
    def _low_threshold(self, settings):
        settings.LOGIN_LOCKOUT_DISTINCT_IPS = 3

    def _make_user(self):
        return CustomUser.objects.create_user(
            email="lockme@railtech.test",
            username="lockme@railtech.test",
            password="Right-pw-123!",
        )

    def test_distinct_ip_failures_lock_then_block_even_correct_password(self):
        user = self._make_user()
        client = APIClient()
        url = reverse("token_obtain_pair")

        for i in range(3):  # 3 DISTINCT IPs == threshold
            resp = client.post(
                url, {"email": user.email, "password": "wrong"}, format="json", REMOTE_ADDR=f"198.51.100.{i}"
            )
            assert resp.status_code == 401

        # Locked: the CORRECT password from any IP is now refused with a generic 429.
        resp = client.post(
            url, {"email": user.email, "password": "Right-pw-123!"}, format="json", REMOTE_ADDR="198.51.100.99"
        )
        assert resp.status_code == 429
        assert resp["Retry-After"]
        assert resp.data["detail"] == "TOO_MANY_LOGIN_ATTEMPTS"

    def test_single_ip_flood_does_not_lock(self):
        # DoS regression guard: many failures from ONE IP must not lock the account,
        # and the legitimate user can still log in.
        user = self._make_user()
        client = APIClient()
        url = reverse("token_obtain_pair")

        for _ in range(5):  # one IP, under the per-IP throttle's 10/min
            resp = client.post(
                url, {"email": user.email, "password": "wrong"}, format="json", REMOTE_ADDR="203.0.113.5"
            )
            assert resp.status_code == 401

        assert login_guard.is_locked(user.email) is False
        resp = client.post(
            url, {"email": user.email, "password": "Right-pw-123!"}, format="json", REMOTE_ADDR="203.0.113.5"
        )
        assert resp.status_code == 200

    def test_successful_login_resets_counter(self):
        user = self._make_user()
        client = APIClient()
        url = reverse("token_obtain_pair")

        for i in range(2):  # below the distinct-IP threshold
            client.post(url, {"email": user.email, "password": "wrong"}, format="json", REMOTE_ADDR=f"192.0.2.{i}")

        resp = client.post(url, {"email": user.email, "password": "Right-pw-123!"}, format="json")
        assert resp.status_code == 200
        assert login_guard.is_locked(user.email) is False

    def test_locked_response_identical_for_real_and_bogus_email(self):
        # No enumeration: the locked HTTP response must not differ by account existence.
        real = self._make_user()
        client = APIClient()
        url = reverse("token_obtain_pair")

        def lock_and_probe(email):
            for i in range(3):
                client.post(url, {"email": email, "password": "wrong"}, format="json", REMOTE_ADDR=f"198.51.100.{i}")
            return client.post(
                url, {"email": email, "password": "whatever"}, format="json", REMOTE_ADDR="198.51.100.200"
            )

        real_resp = lock_and_probe(real.email)
        cache.clear()  # reset throttle/lock state between the two probes
        bogus_resp = lock_and_probe("ghost@nowhere.tld")

        assert real_resp.status_code == bogus_resp.status_code == 429
        assert real_resp.data == bogus_resp.data
        assert real_resp["Retry-After"] == bogus_resp["Retry-After"]


@pytest.mark.django_db
def test_django_auth_failure_signal_logs_for_detection(caplog):
    """A failed Django authenticate() (e.g. /admin/login/) is logged for alerting."""
    import logging

    from django.contrib.auth import authenticate

    with caplog.at_level(logging.WARNING, logger="security"):
        result = authenticate(username="ghost@nowhere.tld", password="nope")

    assert result is None
    assert any("Django auth login failed" in record.getMessage() for record in caplog.records)
