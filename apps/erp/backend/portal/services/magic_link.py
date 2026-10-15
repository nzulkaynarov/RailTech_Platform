"""Magic Link authentication service (CONTRACTS §4, M2-ERP-01)."""

import logging
import secrets
from typing import Tuple

from django.conf import settings
from django.core import mail
from django.utils import timezone
from parties.models import Contact
from portal.exceptions import PortalGone
from portal.models import MagicLinkToken, PortalSession

logger = logging.getLogger(__name__)


def request_magic_link(email: str) -> bool:
    """Создаёт одноразовую ссылку на 15 минут и отправляет письмо.

    Всегда возвращает True (200), чтобы не раскрывать наличие адреса в базе.
    """
    clean_email = email.strip().lower()
    contact = Contact.objects.filter(email__iexact=clean_email).select_related("company").first()

    if not contact or not contact.company:
        logger.info("Magic link requested for unknown email: %s", clean_email)
        return True

    # Инвалидируем старые неиспользованные токены этого контакта
    MagicLinkToken.objects.filter(contact=contact, used_at__isnull=True).update(used_at=timezone.now())

    token = secrets.token_urlsafe(32)
    expires_at = timezone.now() + timezone.timedelta(minutes=15)

    MagicLinkToken.objects.create(
        token=token,
        contact=contact,
        expires_at=expires_at,
    )

    cabinet_url = getattr(settings, "CABINET_URL", "http://cabinet.localhost").rstrip("/")
    login_url = f"{cabinet_url}/auth/magic/{token}"

    subject = "Вход в личный кабинет"
    if contact.language == "uz":
        subject = "Shaxsiy kabinetga kirish"
    elif contact.language == "en":
        subject = "Log in to your client cabinet"

    message = (
        f"Здравствуйте, {contact.name}!\n\n"
        f"Для входа в личный кабинет компании {contact.company.name} перейдите по ссылке:\n"
        f"{login_url}\n\n"
        "Ссылка действительна в течение 15 минут и может быть использована только один раз.\n"
        "Если вы не запрашивали вход, проигнорируйте это письмо."
    )

    try:
        mail.send_mail(
            subject=subject,
            message=message,
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@platform.local"),
            recipient_list=[clean_email],
            fail_silently=True,
        )
    except Exception as exc:
        logger.warning("Failed to send magic link email to %s: %s", clean_email, exc)

    return True


def exchange_magic_link(
    token: str,
    ip_address: str = None,
    user_agent: str = "",
) -> Tuple[PortalSession, str]:
    """Обменивает одноразовый токен magic-link на сессию портала (410 при просрочке/повторе)."""
    token_obj = MagicLinkToken.objects.filter(token=token).select_related("contact__company").first()

    if not token_obj or not token_obj.is_valid():
        logger.info("Magic link token invalid or expired: %s", token)
        raise PortalGone("MAGIC_LINK_EXPIRED")

    # Помечаем использованным
    token_obj.used_at = timezone.now()
    token_obj.save(update_fields=["used_at"])

    contact = token_obj.contact
    company = contact.company

    session_token = secrets.token_hex(32)
    max_age_days = getattr(settings, "PORTAL_SESSION_MAX_AGE_DAYS", 14)
    expires_at = timezone.now() + timezone.timedelta(days=max_age_days)

    session = PortalSession.objects.create(
        token=session_token,
        contact=contact,
        company=company,
        auth_method="magic_link",
        ip_address=ip_address,
        user_agent=user_agent,
        expires_at=expires_at,
    )

    contact.last_login_at = timezone.now()
    contact.save(update_fields=["last_login_at"])

    return session, session_token
