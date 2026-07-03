"""SEC-06 — per-account login lockout (defense-in-depth over the per-IP throttle).

The `login` ScopedRateThrottle (10/min per IP, core/settings.py) blunts a
single-source brute-force but does NOT protect one victim account against a
*distributed* attack (many IPs, few tries each). This adds a per-account layer:
after N failed logins for the same email within a rolling window, that account is
temporarily locked regardless of source IP.

Design (OWASP "Authentication — account lockout", NIST 800-63B rate-limiting):
    * Counters live in the Redis `default` cache — same store the throttles use,
      no new dependency (django-axes was rejected for Django 6.0 compat risk).
    * Threshold / window / cooldown are env-tunable with conservative defaults
      (10 failures / 15-min window → 15-min lock) so an ordinary user fat-
      fingering a password is nowhere near the limit.
    * SHORT, temporary lock only — never a permanent one. A per-account lock is
      inherently a small DoS lever (an attacker can burn a victim's session by
      failing on purpose), so the blast radius is bounded to the cooldown and the
      per-IP throttle already makes sustaining failures expensive. This is the
      accepted trade for stopping distributed credential-stuffing; monitoring
      (a logged security event on every lock) is the compensating control.
    * No account enumeration: failures are recorded and the lock applies for ANY
      submitted email, whether or not a user exists, and the response is generic
      — an attacker cannot tell "locked because real account" from "locked
      because I hammered a bogus address".
    * The email is never used as a raw cache key (key-injection / PII at rest):
      it is normalized and hashed.
"""

import hashlib
import logging

from django.conf import settings
from django.core.cache import cache
from rest_framework import status
from rest_framework.response import Response

logger = logging.getLogger("security")

_COUNTER_PREFIX = "login_fail:"
_LOCK_PREFIX = "login_lock:"


def _threshold() -> int:
    return int(getattr(settings, "LOGIN_LOCKOUT_THRESHOLD", 10))


def _window() -> int:
    return int(getattr(settings, "LOGIN_LOCKOUT_WINDOW", 900))


def _cooldown() -> int:
    return int(getattr(settings, "LOGIN_LOCKOUT_COOLDOWN", 900))


def _identifier(email: str) -> str:
    """Normalize + hash the email so it is safe (and non-PII) as a cache key."""
    normalized = (email or "").strip().lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:32]


def is_locked(email: str) -> bool:
    """True if `email` is currently in a lockout cooldown."""
    if not email:
        return False
    return cache.get(_LOCK_PREFIX + _identifier(email)) is not None


def record_failure(email: str) -> None:
    """Register one failed login for `email`; lock the account once it crosses the threshold."""
    if not email:
        return
    ident = _identifier(email)
    counter_key = _COUNTER_PREFIX + ident
    # `add` is a no-op if the key exists (atomic SETNX) so concurrent misses can't
    # reset a live counter; `incr` on the guaranteed-present key is atomic.
    cache.add(counter_key, 0, timeout=_window())
    try:
        failures = cache.incr(counter_key)
    except ValueError:
        # Key expired between add and incr (window boundary) — treat as a fresh count.
        cache.set(counter_key, 1, timeout=_window())
        failures = 1

    if failures >= _threshold():
        cache.set(_LOCK_PREFIX + ident, 1, timeout=_cooldown())
        cache.delete(counter_key)  # fresh slate once the cooldown elapses
        logger.warning(
            "SEC-06 login lockout engaged: account_hash=%s after %d failures (cooldown=%ds)",
            ident,
            failures,
            _cooldown(),
        )


def reset(email: str) -> None:
    """Clear the failure counter and any lock — call on a successful login."""
    if not email:
        return
    ident = _identifier(email)
    cache.delete_many([_COUNTER_PREFIX + ident, _LOCK_PREFIX + ident])


def locked_response() -> Response:
    """Generic 429 for a locked account (no enumeration), with a Retry-After hint."""
    cooldown = _cooldown()
    response = Response(
        {"detail": "TOO_MANY_LOGIN_ATTEMPTS"},
        status=status.HTTP_429_TOO_MANY_REQUESTS,
    )
    response["Retry-After"] = str(cooldown)
    return response
