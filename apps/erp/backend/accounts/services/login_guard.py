"""SEC-06 — per-account login lockout keyed on DISTINCT source IPs.

The `login` ScopedRateThrottle (10/min per IP, core/settings.py) already stops a
single-source brute-force. This layer exists for the one thing the per-IP throttle
cannot see: a DISTRIBUTED credential-stuffing run — many IPs, a few tries each —
against one victim account. So the account lock trips on the number of DISTINCT
IPs that fail for an email, NOT on the raw failure count.

Why distinct-IP and not raw attempts (adversarial-review finding, 2026-07-03):
    A raw-attempt counter let a SINGLE IP — well within its own 10/min budget —
    lock any account permanently (re-hit the threshold each cooldown). Since a
    B2B counterparty's email is semi-public (invites, quotes, contracts, chat),
    that turned "attacker needs the password to deny login" into "attacker needs
    only the email" — a targeted-DoS regression. Counting distinct IPs removes
    that: a one-IP flood never advances the lock (the per-IP throttle handles it),
    and locking a victim now costs the attacker THRESHOLD distinct IPs — i.e. it
    only trips when a genuinely distributed attack is already underway, which is
    exactly when locking is the correct response.

Design (OWASP auth-lockout / NIST 800-63B rate-limiting; django-axes was rejected
for Django 6.0 compat risk):
    * State lives in the Redis `default` cache (same store the throttles use). The
      per-account key holds the SET of distinct IPs seen failing in the window;
      once |IPs| >= LOGIN_LOCKOUT_DISTINCT_IPS the account is locked for
      LOGIN_LOCKOUT_COOLDOWN. All keys carry TTLs (window / cooldown) — bounded,
      self-expiring, and the set is capped at the threshold, so no cache-flood.
    * Fixed window anchored at the first failure (the TTL is not refreshed on each
      failure) — NOT a rolling window. This is deliberate: it reliably catches the
      fast distributed burst that is this layer's job. It does NOT try to stop a
      patient low-and-slow grind that paces under the threshold; that residual is
      inherent to any count-based lockout and is left to the per-IP throttle,
      strong-password policy, and the alerting below.
    * Every lock is logged at ERROR so prod Sentry raises it as an ALERT (a
      WARNING would only be a breadcrumb) — this is the compensating monitoring
      control for the availability trade-off. It logs the sha256 `account_hash`,
      never the raw email / password / token.
    * No account enumeration: failures are recorded and the lock applies for ANY
      submitted email (real or bogus) and the 429 response is generic.
    * The email is normalized (trim + lowercase) and sha256-hashed — never a raw
      cache key (PII at rest / key injection). Lockout identity is therefore
      case-insensitive: variants of one address share a lock.

Operational note (S0-2): the `default` cache is the dedicated `redis-cache` instance
(`volatile-lru`; Channels and Celery live on `redis-broker`). All lockout keys are
TTL-bounded and tiny, so they are evicted only if the whole cache overflows. The cache is
fail-open (`core.cache`): while `redis-cache` is down the lockout is skipped, exactly like the
DRF throttles, and the password / TOTP checks themselves stay in force.
"""

import hashlib
import logging

from django.conf import settings
from django.core.cache import cache
from rest_framework import status
from rest_framework.response import Response

logger = logging.getLogger("security")

_COUNTER_PREFIX = "login_fail_ips:"
_LOCK_PREFIX = "login_lock:"


def _distinct_ip_threshold() -> int:
    return int(getattr(settings, "LOGIN_LOCKOUT_DISTINCT_IPS", 10))


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


def record_failure(email: str, ip: str) -> None:
    """Register one failed login for `email` from source `ip`.

    Locks the account only once LOGIN_LOCKOUT_DISTINCT_IPS *distinct* IPs have
    failed within the window — repeated failures from the same IP do not advance
    the count (that is the per-IP throttle's job).
    """
    if not email or not ip:
        return
    ident = _identifier(email)
    counter_key = _COUNTER_PREFIX + ident

    seen_ips = cache.get(counter_key)
    if not isinstance(seen_ips, set):
        seen_ips = set()
    if ip in seen_ips:
        return  # this IP already counts toward this window — don't re-lock on repeats
    seen_ips.add(ip)
    # Fixed window: set the TTL once, anchored at the first failure (get→set is not
    # perfectly atomic, but a lost concurrent IP only UNDER-counts, favouring the user).
    cache.set(counter_key, seen_ips, timeout=_window())

    if len(seen_ips) >= _distinct_ip_threshold():
        cache.set(_LOCK_PREFIX + ident, 1, timeout=_cooldown())
        cache.delete(counter_key)  # fresh slate once the cooldown elapses
        logger.error(
            "SEC-06 login lockout engaged: account_hash=%s locked after failures from "
            "%d distinct IPs (cooldown=%ds) — possible distributed credential-stuffing",
            ident,
            len(seen_ips),
            _cooldown(),
        )


def reset(email: str) -> None:
    """Clear the distinct-IP set and any lock — call on a successful login."""
    if not email:
        return
    ident = _identifier(email)
    cache.delete_many([_COUNTER_PREFIX + ident, _LOCK_PREFIX + ident])


def note_django_auth_failure(username: str, ip: str, path: str) -> None:
    """Detection-only hook for Django-auth (e.g. /admin/login/) failures.

    Django's authenticate() fires `user_login_failed` on failure; simplejwt (the
    DRF app login) does NOT, so this covers the Unfold admin login and any
    management auth WITHOUT double-counting the DRF path already handled by
    record_failure(). We LOG for alerting but deliberately do NOT lock: the sole
    superadmin is the break-glass account and must stay reachable at /admin/login/
    — a hard lock there would be a self-inflicted DoS. Per-IP rate limiting for
    /admin/ belongs at the edge (host Caddy). Logs the hashed identity only.
    """
    ident = _identifier(username) if username else "?"
    logger.warning("Django auth login failed: account_hash=%s ip=%s path=%s", ident, ip or "?", path or "?")


def locked_response() -> Response:
    """Generic 429 for a locked account (no enumeration), with a Retry-After hint."""
    cooldown = _cooldown()
    response = Response(
        {"detail": "TOO_MANY_LOGIN_ATTEMPTS"},
        status=status.HTTP_429_TOO_MANY_REQUESTS,
    )
    response["Retry-After"] = str(cooldown)
    return response
