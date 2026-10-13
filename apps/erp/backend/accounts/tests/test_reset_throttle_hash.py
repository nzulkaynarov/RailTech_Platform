"""SEC-tail: the password-reset per-email throttle keys on a sha256 hash, not
plaintext PII.

The throttle shields a victim's inbox by counting resets per TARGET email across
IPs. It used to write the lowercased email straight into the Redis cache key
(PII at rest). Hashing keeps the key deterministic — so throttling is unchanged —
while never persisting the raw address.
"""

import hashlib

import pytest
from django.core.cache import cache
from django.test import override_settings
from rest_framework.test import APIClient

from accounts.throttles import PasswordResetEmailThrottle

LOCMEM = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}


class _FakeRequest:
    def __init__(self, data):
        self.data = data


def test_cache_key_hashes_email_no_plaintext():
    throttle = PasswordResetEmailThrottle()
    email = "Victim@Example.com"
    key = throttle.get_cache_key(_FakeRequest({"email": email}), view=None)
    expected_hash = hashlib.sha256(email.strip().lower().encode("utf-8")).hexdigest()
    assert expected_hash in key
    # No form of the raw address (any case) may appear in the cache key.
    assert "victim@example.com" not in key.lower()
    assert "@" not in key


def test_cache_key_deterministic_and_case_insensitive():
    """Same address (mixed case / whitespace) → same key, so the 3/hour cap still
    aggregates every request for one victim regardless of formatting or IP."""
    throttle = PasswordResetEmailThrottle()
    a = throttle.get_cache_key(_FakeRequest({"email": "  Victim@Example.com "}), view=None)
    b = throttle.get_cache_key(_FakeRequest({"email": "victim@example.com"}), view=None)
    assert a == b
    other = throttle.get_cache_key(_FakeRequest({"email": "someone-else@example.com"}), view=None)
    assert other != a


def test_missing_email_falls_through_to_ip_throttle():
    throttle = PasswordResetEmailThrottle()
    assert throttle.get_cache_key(_FakeRequest({}), view=None) is None


@override_settings(CACHES=LOCMEM)
@pytest.mark.django_db
def test_endpoint_still_throttles_same_address_with_hashed_key():
    """End-to-end: 3/hour still enforced per address, and the persisted cache key
    carries the hash — never the plaintext email."""
    cache.clear()
    client = APIClient()
    payload = {"email": "target@example.com"}
    first_three = [client.post("/api/v1/auth/forgot-password/", payload, format="json").status_code for _ in range(3)]
    assert all(code != 429 for code in first_three), first_three
    blocked = client.post("/api/v1/auth/forgot-password/", payload, format="json")
    assert blocked.status_code == 429

    expected_hash = hashlib.sha256(b"target@example.com").hexdigest()
    hashed_key = PasswordResetEmailThrottle.cache_format % {
        "scope": "password_reset_email",
        "ident": expected_hash,
    }
    assert cache.get(hashed_key) is not None  # counter stored under the hashed key
    cache.clear()
