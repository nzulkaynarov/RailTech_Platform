"""Anti-abuse throttling on sensitive auth endpoints (Sprint D).

Owner-flagged: the password-reset window could send unlimited emails. These tests
pin the tight per-endpoint limits that stop that class of fraud.
"""

import pytest
from django.core.cache import cache
from django.test import override_settings
from rest_framework.test import APIClient

# Isolated in-memory cache so throttle history doesn't leak across tests / runs
# (the real RedisCache would persist counts between runs and make this flaky).
LOCMEM = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


@override_settings(CACHES=LOCMEM)
@pytest.mark.django_db
def test_forgot_password_throttled_per_target_email():
    """password_reset_email = 3/hour: a 4th reset request for the same address is
    rejected, so a victim's inbox can't be bombed (even across rotating IPs)."""
    client = APIClient()
    payload = {"email": "victim@example.com"}
    statuses = [client.post("/api/v1/auth/forgot-password/", payload, format="json").status_code for _ in range(3)]
    assert all(s != 429 for s in statuses), statuses  # first 3 allowed
    blocked = client.post("/api/v1/auth/forgot-password/", payload, format="json")
    assert blocked.status_code == 429


@override_settings(CACHES=LOCMEM)
@pytest.mark.django_db
def test_login_throttled_per_ip():
    """login = 10/min per IP: brute-force is capped (11th attempt → 429)."""
    client = APIClient()
    creds = {"email": "nobody@example.com", "password": "wrong"}
    last = None
    for _ in range(11):
        last = client.post("/api/v1/auth/token/", creds, format="json")
    assert last.status_code == 429
