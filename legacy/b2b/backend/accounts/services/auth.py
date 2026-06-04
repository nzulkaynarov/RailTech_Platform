import logging
from typing import Optional, Tuple

from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode

from notifications.emails import EmailDeliveryError, send_templated_email

from ..models import CustomUser, SystemRole

logger = logging.getLogger(__name__)


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


def create_pending_user(
    email: str, first_name: str, last_name: str, phone: str = ""
) -> Tuple[Optional[CustomUser], Optional[str]]:
    """
    Step 1: Create a user in a pending state and send verification email.
    """
    if not email or not first_name or not last_name:
        return None, "REGISTRATION_FIELDS_REQUIRED"

    if CustomUser.objects.filter(email=email).exists():
        return None, "USER_EMAIL_ALREADY_EXISTS"

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

    token = default_token_generator.make_token(user)
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    base_url = settings.FRONTEND_URL
    setup_url = f"{base_url}/setup-password?uid={uid}&token={token}"

    try:
        send_templated_email(
            "setup_password",
            {"first_name": first_name, "setup_url": setup_url},
            to=[email],
            channel="transactional",
            user=user,
        )
    except EmailDeliveryError:
        # Email failed — clean up the orphaned user so they can retry
        user.delete()
        return None, "EMAIL_SEND_FAILED"

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

    try:
        send_templated_email(
            "reset_password",
            {"first_name": user.first_name or "", "reset_url": reset_url},
            to=[user.email],
            channel="transactional",
            user=user,
        )
    except EmailDeliveryError:
        logger.exception("Failed to send password reset email to %s", user.email)
        return False, "EMAIL_SEND_FAILED"
    return True, None


def reset_password(uidb64: str, token: str, password: str) -> Tuple[Optional[CustomUser], Optional[str]]:
    """Verify reset token and set a new password. Reuses Django's default token generator."""
    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        user = CustomUser.objects.get(pk=uid)
    except (TypeError, ValueError, OverflowError, CustomUser.DoesNotExist):
        return None, "RESET_PASSWORD_INVALID_USER"
    if not default_token_generator.check_token(user, token):
        return None, "RESET_PASSWORD_INVALID_TOKEN"
    if not password or len(password) < 8:
        return None, "RESET_PASSWORD_WEAK"
    user.set_password(password)
    if not user.is_active:
        user.is_active = True
    user.save(update_fields=["password", "is_active"])
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

    user.set_password(password)
    user.is_active = True
    user.save()
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
    user.set_password(new_password)
    user.save(update_fields=["password"])
    revoke_user_refresh_tokens(user)
    return user, None
