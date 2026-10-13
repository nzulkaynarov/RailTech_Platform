"""Active-session management on top of simplejwt's token blacklist (Rule 8).

A "session" is an outstanding (non-blacklisted, non-expired) refresh token. There
is no ip/user-agent capture — OutstandingToken stores only jti + timestamps, so the
UI shows creation/expiry and which row is the CURRENT browser (matched by the jti
of the HttpOnly refresh cookie).
"""

from django.utils import timezone
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken


def active_sessions(user):
    """Queryset of the user's live refresh tokens, newest first."""
    return (
        OutstandingToken.objects.filter(user=user, expires_at__gt=timezone.now())
        .filter(blacklistedtoken__isnull=True)
        .order_by("-created_at")
    )


def revoke_other_sessions(user, keep_jti: str | None) -> int:
    """Blacklist every live refresh token EXCEPT the current one (keep_jti), so
    "log out everywhere else" does not also kill the session that clicked it.
    With keep_jti=None revokes everything. Returns the number revoked."""
    tokens = active_sessions(user)
    if keep_jti:
        tokens = tokens.exclude(jti=keep_jti)
    revoked = 0
    for token in tokens:
        _, created = BlacklistedToken.objects.get_or_create(token=token)
        if created:
            revoked += 1
    return revoked
