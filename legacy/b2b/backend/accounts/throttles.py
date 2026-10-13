"""Anti-abuse throttles for sensitive unauthenticated auth endpoints.

The global AnonRateThrottle (20/min) is far too loose to stop targeted abuse like
password-reset email bombing. These add tight, purpose-built limits.
"""

import hashlib

from rest_framework.throttling import ScopedRateThrottle, SimpleRateThrottle


class PasswordResetEmailThrottle(SimpleRateThrottle):
    """Throttle forgot-password by the TARGET email, not the requester IP.

    An IP-based throttle alone lets an attacker rotate IPs to keep bombing one
    victim's inbox. Keying on the requested email caps how many reset emails any
    single address can receive per window, regardless of source IP.
    """

    scope = "password_reset_email"

    def get_cache_key(self, request, view):
        email = (request.data.get("email") or "").strip().lower()
        if not email:
            return None  # nothing to key on → fall through to the IP-scoped throttle
        # SEC-tail: hash the email before using it as the cache ident so no plaintext
        # address (PII) is ever written to Redis. sha256 is deterministic → the same
        # address maps to the same key, so throttling still works exactly as before.
        ident = hashlib.sha256(email.encode("utf-8")).hexdigest()
        return self.cache_format % {"scope": self.scope, "ident": ident}


# IP-scoped throttle whose rate is taken from the view's `throttle_scope`
# (DEFAULT_THROTTLE_RATES). Re-exported so views import everything from one place.
__all__ = ["PasswordResetEmailThrottle", "ScopedRateThrottle"]
