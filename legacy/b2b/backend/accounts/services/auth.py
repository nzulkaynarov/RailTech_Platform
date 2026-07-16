from typing import Optional, Tuple

from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode

from notifications.tasks import send_transactional_email

from ..models import CustomUser, SystemRole


def _password_error(password: str, user: Optional[CustomUser] = None) -> Optional[str]:
    """Enforce AUTH_PASSWORD_VALIDATORS on EVERY password-setting path (SEC-01).

    The validators were declared in settings.py but never invoked — only an 8-char
    min was checked, so `password`, `12345678`, `aaaaaaaa` slipped through. Returns a
    stable error CODE on failure (i18n `apiErrors.PASSWORD_TOO_WEAK`), else None — the
    callers surface it as (None, code) rather than raising, matching their contract.
    """
    if not password or len(password) < 8:
        return "PASSWORD_TOO_WEAK"
    try:
        validate_password(password, user)
    except DjangoValidationError:
        return "PASSWORD_TOO_WEAK"
    return None


def revoke_user_refresh_tokens(user: CustomUser) -> int:
    """Blacklist every outstanding refresh token for the user.

    Called after a password reset/change so previously issued refresh tokens
    cannot be rotated into fresh access tokens by anyone holding a stolen copy.
    Requires `rest_framework_simplejwt.token_blacklist` (installed).
    Returns the number of tokens newly blacklisted.
    """
    from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken

    revoked = 0
    outstanding = OutstandingToken.objects.filter(user=user).exclude(blacklistedtoken__isnull=False)
    for token in outstanding:
        _, created = BlacklistedToken.objects.get_or_create(token=token)
        if created:
            revoked += 1
    return revoked


def _enqueue_setup_email(user: CustomUser) -> None:
    """Enqueue the password-setup link for a pending (never-activated) user.

    Off-thread send (SEC-tail): never block the ASGI worker on SMTP in the request
    path. The Celery task retries with backoff — strictly more robust than the old
    inline single-attempt, which deleted the user on the first transport hiccup.
    """
    token = default_token_generator.make_token(user)
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    setup_url = f"{settings.FRONTEND_URL}/setup-password?uid={uid}&token={token}"
    send_transactional_email.delay(
        "setup_password",
        {"first_name": user.first_name or "", "setup_url": setup_url},
        [user.email],
        channel="transactional",
        user_id=user.pk,
    )


def _enqueue_existing_account_email(user: CustomUser) -> None:
    """Notify the REAL owner that a (re-)registration hit an already-active email.

    Anti-enumeration (P2): registration must not reveal that this email is taken.
    Instead of a 400 to the requester, the genuine account holder gets a neutral
    "your account already exists — sign in or recover your password" email with
    login / forgot-password links. Enqueued (never inline) so both the free-email
    and taken-email paths return in constant time — the same timing-channel close
    as the neutral-200 forgot-password flow.
    """
    base_url = settings.FRONTEND_URL
    send_transactional_email.delay(
        "register_existing_account",
        {
            "first_name": user.first_name or "",
            "login_url": f"{base_url}/",
            "forgot_url": f"{base_url}/forgot-password",
        },
        [user.email],
        channel="transactional",
        user_id=user.pk,
    )


def create_pending_user(
    email: str, first_name: str, last_name: str, phone: str = ""
) -> Tuple[Optional[CustomUser], Optional[str]]:
    """Register by email WITHOUT leaking whether the address already has an account.

    Anti-enumeration (P2, industry standard — GitHub/Google): the endpoint returns
    the SAME neutral success regardless of which of three branches runs, and the
    two "occupied" branches ONLY enqueue an email (constant-time), so neither the
    status/body nor the timing distinguishes them:

    * email free            → create the pending user + send the setup-link;
    * email = ACTIVE account → send `register_existing_account` (sign-in / recover);
                               do NOT create a second user;
    * email = PENDING account → re-send the setup-link (idempotent re-registration —
                               fixes the dead-end where a lost first email left the
                               user unable to finish signing up).

    Only a genuinely malformed request (missing fields — normally caught by the
    serializer) returns an error code; the caller maps that to 400.
    """
    if not email or not first_name or not last_name:
        return None, "REGISTRATION_FIELDS_REQUIRED"

    existing = CustomUser.objects.filter(email__iexact=email).first()
    if existing is not None:
        if existing.is_active:
            _enqueue_existing_account_email(existing)
        else:
            _enqueue_setup_email(existing)
        return existing, None

    # Default system role at registration: USER.
    user_role = SystemRole.objects.filter(code="USER").first()

    user = CustomUser.objects.create(
        username=email,
        email=email,
        first_name=first_name,
        last_name=last_name,
        phone=phone,
        is_active=False,
        role=user_role,
    )
    user.set_unusable_password()
    user.save()

    _enqueue_setup_email(user)

    return user, None


def send_password_reset_email(email: str) -> Tuple[bool, Optional[str]]:
    """
    Triggers a password-reset email for an existing active user. Silently
    succeeds when the email is unknown to avoid user enumeration.
    Returns: (delivered, error_code_or_None). `delivered=False` + no error
    means email was unknown; we still return True/None to the caller so the
    frontend shows the same outcome either way.
    """
    email = (email or "").strip().lower()
    if not email:
        return False, "EMAIL_REQUIRED"
    user = CustomUser.objects.filter(email__iexact=email).first()
    if not user:
        # Do not leak account existence — caller should show "if an account
        # exists, a link was sent" regardless.
        return True, None
    if not user.is_active:
        return True, None

    token = default_token_generator.make_token(user)
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    base_url = settings.FRONTEND_URL
    reset_url = f"{base_url}/reset-password?uid={uid}&token={token}"

    # Off-thread send (SEC-tail): the synchronous SMTP round-trip here was the timing
    # side-channel that defeated the neutral-200 response — a KNOWN email did the slow
    # send while an UNKNOWN one returned instantly. Enqueuing makes both paths return
    # in constant time, and the request no longer blocks the ASGI worker on SMTP.
    send_transactional_email.delay(
        "reset_password",
        {"first_name": user.first_name or "", "reset_url": reset_url},
        [user.email],
        channel="transactional",
        user_id=user.pk,
    )
    return True, None


def reset_password(uidb64: str, token: str, password: str) -> Tuple[Optional[CustomUser], Optional[str]]:
    """Verify reset token and set a new password. Reuses Django's default token generator."""
    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        user = CustomUser.objects.get(pk=uid)
    except (TypeError, ValueError, OverflowError, CustomUser.DoesNotExist):
        return None, "RESET_PASSWORD_INVALID_USER"
    # SEC-12: a password reset must not resurrect a deactivated account — deactivation
    # (operator ban / offboarding) is reversible only by a platform operator. The old
    # code silently flipped is_active=True here. Never-activated registrations go
    # through verify_and_setup_password, not this flow. Same generic code as an
    # unknown user so account state doesn't leak.
    if not user.is_active:
        return None, "RESET_PASSWORD_INVALID_USER"
    if not default_token_generator.check_token(user, token):
        return None, "RESET_PASSWORD_INVALID_TOKEN"
    weak = _password_error(password, user)
    if weak:
        return None, weak
    user.set_password(password)
    user.save(update_fields=["password"])
    revoke_user_refresh_tokens(user)
    return user, None


def verify_and_setup_password(uidb64: str, token: str, password: str) -> Tuple[Optional[CustomUser], Optional[str]]:
    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        user = CustomUser.objects.get(pk=uid)
    except (TypeError, ValueError, OverflowError, CustomUser.DoesNotExist):
        return None, "SETUP_PASSWORD_INVALID_USER"

    if not default_token_generator.check_token(user, token):
        return None, "SETUP_PASSWORD_INVALID_TOKEN"

    weak = _password_error(password, user)
    if weak:
        return None, weak

    user.set_password(password)
    user.is_active = True
    user.save()
    # SEC-05: treat setup like reset — invalidate any refresh tokens so a leaked/replayed
    # setup link can't keep a session alive after the password is set.
    revoke_user_refresh_tokens(user)
    return user, None


def change_user_password(
    user: CustomUser,
    current_password: str,
    new_password: str,
) -> Tuple[Optional[CustomUser], Optional[str]]:
    """
    Change user password after verifying the current one.
    Returns: (user, error_or_None)
    """
    if not user.check_password(current_password):
        return None, "CURRENT_PASSWORD_WRONG"
    weak = _password_error(new_password, user)
    if weak:
        return None, weak
    user.set_password(new_password)
    user.save(update_fields=["password"])
    revoke_user_refresh_tokens(user)
    return user, None
