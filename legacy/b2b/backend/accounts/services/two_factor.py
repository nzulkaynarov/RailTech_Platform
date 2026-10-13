"""Two-factor authentication (TOTP) services — Rule 8: all 2FA logic lives here.

Flow (frontend `LoginPage` → `authStore`):
    1. POST /auth/token/ with a correct password for a 2FA-enabled account does NOT
       return tokens. The freshly minted pair is voided (refresh blacklisted) and the
       caller receives ``{"2fa_required": true, "temp_token": <signed ticket>}``.
    2. POST /auth/login/2fa/ exchanges ticket + 6-digit TOTP code for the real pair
       (access in body, refresh in the HttpOnly cookie — F2.1, never in the body).

The ticket is a salted, timestamped signature of the user id — it proves "password
already verified" for TICKET_MAX_AGE seconds and nothing else. Brute-forcing the
6-digit code during that window is blunted by the per-IP `login` throttle plus the
SEC-06 per-account lockout (both applied by the view, same as password login).

The TOTP secret is encrypted at rest (Fernet, key derived from SECRET_KEY) — a DB
dump/SQLi read must not be enough to mint valid codes. Rotating SECRET_KEY makes
stored secrets undecryptable: those users' codes stop matching and they must
re-enroll (support disables 2FA after identity re-verification).
"""

import base64
import binascii
import hashlib
import secrets

import pyotp
from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.signing import BadSignature, SignatureExpired, TimestampSigner
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

# How long the "password already verified" ticket stays valid (seconds).
TICKET_MAX_AGE = 300

# TOTP tolerance: accept the previous/next 30s step — standard clock-drift allowance.
TOTP_VALID_WINDOW = 1

# A used TOTP code is remembered just long enough to cover the accepted step plus
# the ±1 clock-drift window (3 × 30s), so the same code can never be replayed while
# it is still arithmetically valid.
USED_CODE_TTL = 90

_TICKET_SALT = "accounts.two_factor.login"

# Redis cache keys (SEC-06 replay hardening). Both share the `default` cache with the
# login lockout / throttles — a Redis outage already fails login closed system-wide
# (login_guard.is_locked reads the same store), so there is no fail-open replay path.
_TICKET_USED_PREFIX = "2fa_ticket_used:"
_USED_CODE_PREFIX = "2fa_used_code:"


def _signer() -> TimestampSigner:
    return TimestampSigner(salt=_TICKET_SALT)


def _fernet() -> Fernet:
    key = base64.urlsafe_b64encode(hashlib.sha256(settings.SECRET_KEY.encode()).digest())
    return Fernet(key)


def encrypt_totp_secret(plain_secret: str) -> str:
    return _fernet().encrypt(plain_secret.encode()).decode()


def decrypt_totp_secret(stored_secret: str) -> str:
    """Stored → plaintext base32. A value that doesn't decrypt is passed through
    as-is: it's either a legacy plaintext row (pre-encryption, migration 0039 not
    yet applied mid-deploy) — which then verifies fine — or garbage after a
    SECRET_KEY rotation, which pyotp rejects as a failed code, never a 500."""
    try:
        return _fernet().decrypt(stored_secret.encode()).decode()
    except InvalidToken:
        return stored_secret


def _code_matches(secret: str, code: str) -> bool:
    if not secret or not code:
        return False
    try:
        return pyotp.TOTP(secret).verify(code, valid_window=TOTP_VALID_WINDOW)
    except (ValueError, binascii.Error):
        # Malformed base32 secret — treat as a failed code, never a 500.
        return False


def generate_totp_setup(user) -> dict:
    """Mint a fresh secret + otpauth:// provisioning URI for the QR code.

    Nothing is persisted — the secret only becomes active after enable_totp()
    confirms the user actually scanned it (proves possession of the device).
    """
    secret = pyotp.random_base32()
    uri = pyotp.totp.TOTP(secret).provisioning_uri(name=user.email, issuer_name="RailTech B2B")
    return {"secret": secret, "uri": uri}


def enable_totp(user, secret: str, code: str, current_password: str) -> str | None:
    """Activate 2FA once the user proves the device generates valid codes.

    Step-up (GitHub sudo-mode): the current password is required IN ADDITION to the
    TOTP code, so a stolen access token alone cannot flip a security setting.
    Returns an error CODE or None on success.
    """
    if user.is_2fa_enabled:
        return "2FA_ALREADY_ENABLED"
    if not current_password:
        return "PASSWORD_REQUIRED"
    if not user.check_password(current_password):
        return "INVALID_PASSWORD"
    if not secret or not code:
        return "2FA_CODE_REQUIRED"
    if not _code_matches(secret, code):
        return "2FA_INVALID_CODE"
    user.totp_secret = encrypt_totp_secret(secret)
    user.is_2fa_enabled = True
    user.save(update_fields=["totp_secret", "is_2fa_enabled"])
    return None


def disable_totp(user, code: str, current_password: str) -> str | None:
    """Turn 2FA off; requires the current password AND a currently valid code
    (step-up — a stolen access token alone must not be able to strip 2FA off)."""
    if not user.is_2fa_enabled or not user.totp_secret:
        return None  # already off — idempotent
    if not current_password:
        return "PASSWORD_REQUIRED"
    if not user.check_password(current_password):
        return "INVALID_PASSWORD"
    if not code:
        return "2FA_CODE_REQUIRED"
    if not _code_matches(decrypt_totp_secret(user.totp_secret), code):
        return "2FA_INVALID_CODE"
    user.is_2fa_enabled = False
    user.totp_secret = None
    user.save(update_fields=["is_2fa_enabled", "totp_secret"])
    return None


def issue_login_ticket(user) -> str:
    """Signed "password verified, awaiting TOTP" ticket for the 2FA login step.

    A random nonce (jti) is embedded so the ticket can be marked single-use in Redis
    on successful redemption — a leaked ticket (proxy/access logs) cannot mint a
    second session even inside its TICKET_MAX_AGE window (SEC-06 replay hardening).
    """
    jti = secrets.token_urlsafe(16)
    return _signer().sign(f"{user.pk}:{jti}")


def redeem_login_ticket(temp_token: str, code: str):
    """Exchange ticket + TOTP code for the user. Returns (user, error_code).

    Every ticket problem (bad signature, expired, unknown/inactive user, 2FA turned
    off meanwhile, ticket already spent) collapses into one 2FA_TICKET_INVALID with
    user=None. A wrong OR already-used code returns ("2FA_INVALID_CODE") WITH the
    resolved user, so the caller can charge the failure against that account's
    SEC-06 lockout.

    Replay hardening (SEC-06): the signed ticket is single-use (its nonce is marked
    spent in Redis on success) and every accepted TOTP code is remembered for
    USED_CODE_TTL so it cannot be replayed while still arithmetically valid. Both
    checks read the `default` cache, the same store login_guard.is_locked() already
    depends on — so a Redis outage fails login closed rather than opening a replay
    hole.
    """
    try:
        payload = _signer().unsign(temp_token or "", max_age=TICKET_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None, "2FA_TICKET_INVALID"
    user_id, _, jti = payload.partition(":")
    if not jti or cache.get(_TICKET_USED_PREFIX + jti) is not None:
        # No nonce (legacy/tampered) or the ticket was already redeemed → invalid.
        return None, "2FA_TICKET_INVALID"
    user = get_user_model().objects.filter(pk=user_id, is_active=True).first()
    if user is None or not user.is_2fa_enabled or not user.totp_secret:
        return None, "2FA_TICKET_INVALID"
    if not _code_matches(decrypt_totp_secret(user.totp_secret), code):
        return user, "2FA_INVALID_CODE"
    # Correct code, but reject it if this exact code was already accepted for this
    # user inside its validity window (pyotp.verify has no memory of used codes).
    used_code_key = f"{_USED_CODE_PREFIX}{user.pk}:{code}"
    if cache.get(used_code_key) is not None:
        return user, "2FA_INVALID_CODE"
    cache.set(used_code_key, 1, timeout=USED_CODE_TTL)
    cache.set(_TICKET_USED_PREFIX + jti, 1, timeout=TICKET_MAX_AGE)
    return user, None


def void_refresh_token(refresh: str | None) -> None:
    """Blacklist a refresh token that must never be used (the pair minted by the
    password step of a 2FA login is discarded, not handed to the client)."""
    if not refresh:
        return
    try:
        RefreshToken(refresh).blacklist()
    except TokenError:
        pass  # already invalid — nothing to void


def refresh_cookie_jti(request) -> str | None:
    """jti of the refresh token in the HttpOnly cookie — identifies the CURRENT
    session so session views can mark/spare it. None if absent or invalid."""
    token = request.COOKIES.get(settings.REFRESH_COOKIE_NAME)
    if not token:
        return None
    try:
        return RefreshToken(token)["jti"]
    except TokenError:
        return None
