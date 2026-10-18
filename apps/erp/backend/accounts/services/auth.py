from typing import Optional, Tuple

from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode

from notifications.tasks import send_transactional_email

from ..models import CustomUser
from .permissions import is_seller

STAFF_ONLY = "STAFF_ONLY"


def assert_staff_login(user: CustomUser) -> None:
    """Вход в ERP — только сотрудникам (FIX-13, инвариант «один главный пользователь»).

    Пустить можно администратора (`is_superuser`) и активного участника своей компании
    (`core.tenant.own_company()`). Участник компании-клиента (контакт, когда-то заведённый как
    пользователь) в ERP не входит: клиент работает в портале. Отказ — 403 `STAFF_ONLY`.
    """
    from rest_framework.exceptions import PermissionDenied

    if getattr(user, "is_superuser", False) or is_seller(user):
        return
    raise PermissionDenied(STAFF_ONLY)


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
    # (offboarding) is reversible only by an administrator. The old code silently flipped
    # is_active=True here. Never-activated invitees go through verify_and_setup_password,
    # not this flow. Same generic code as an
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
    """Set the first password of an invited (never-activated) user and activate the account.

    The link comes from a team invitation (`invite_workspace_member`), an account created by an
    administrator (`create_platform_user`) or the Unfold company wizard. Self-registration is gone
    (M1-ERP-02 wave 1c): employees are provisioned by CRM (ADR-0003) or invited.
    """
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
