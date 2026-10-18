"""Portal Invitation service (CONTRACTS §4, M2-ERP-02).

Manages inviting client contacts into the Cabinet portal via Email and/or Telegram.
Ensures delivery via `send_templated_email` (creating EmailLog in both locales).
Рабочая ссылка входа уходит только клиенту, в письме; сотруднику, API и журналу отдаются факт
отправки и канал (FIX-14, P-11).
"""

from __future__ import annotations

import logging
from typing import Optional, Tuple

from django.conf import settings
from django.utils import timezone
from parties.models import Contact
from portal.models import MagicLinkToken
from portal.services.magic_link import build_login_url
from portal.services.tokens import generate_token, hash_token

from notifications.emails import send_templated_email

logger = logging.getLogger(__name__)


def invite_contact_to_portal(
    contact: Contact,
    actor=None,
    channel: Optional[str] = None,
    language: Optional[str] = None,
) -> Tuple[Optional[dict], Optional[str]]:
    """Пригласить контакт клиента в личный кабинет.

    Возвращает (result, None) или (None, error_code).
    Каналы: 'email', 'telegram', 'both'. По умолчанию берется `contact.preferred_channel`.
    """
    if not contact.company:
        return None, "CONTACT_WITHOUT_COMPANY"
    if not contact.company.is_active:
        return None, "COMPANY_ARCHIVED"

    effective_channel = channel or contact.preferred_channel or "email"
    if effective_channel not in ("email", "telegram", "both"):
        return None, "INVALID_CHANNEL"

    clean_email = (contact.email or "").strip().lower()

    # Проверка достижимости по каналам
    if effective_channel == "email" and not clean_email:
        return None, "CONTACT_EMAIL_REQUIRED"

    has_telegram = bool(
        contact.telegram_user_id
        or contact.telegram_username
        or contact.phone
        or getattr(settings, "TELEGRAM_BOT_USERNAME", "")
    )
    if effective_channel == "telegram" and not has_telegram:
        return None, "CONTACT_TELEGRAM_UNREACHABLE"

    # Если both, но нет email — деградируем на telegram при его наличии, либо ошибка
    if effective_channel == "both" and not clean_email:
        if has_telegram:
            effective_channel = "telegram"
        else:
            return None, "CONTACT_EMAIL_REQUIRED"

    # Ссылка нужна только письму: по Telegram клиент входит подписанным initData (telegram_user_id).
    login_url = None
    if effective_channel in ("email", "both") and clean_email:
        # Гасим только прежние приглашения: ссылка входа, запрошенная клиентом, остаётся рабочей.
        MagicLinkToken.objects.filter(
            contact=contact, purpose=MagicLinkToken.PURPOSE_INVITE, used_at__isnull=True
        ).update(used_at=timezone.now())

        # Токен приглашения (действителен 24 часа); в базе — только хеш
        raw_token = generate_token()
        MagicLinkToken.objects.create(
            token_hash=hash_token(raw_token),
            contact=contact,
            purpose=MagicLinkToken.PURPOSE_INVITE,
            expires_at=timezone.now() + timezone.timedelta(hours=24),
        )
        login_url = build_login_url(raw_token)

    bot_username = getattr(settings, "TELEGRAM_BOT_USERNAME", "")
    telegram_url = f"https://t.me/{bot_username}" if bot_username else None

    email_sent = False
    if effective_channel in ("email", "both") and clean_email:
        target_language = language or contact.language or "ru"
        try:
            send_templated_email(
                "portal_invitation",
                context={
                    "contact_name": contact.name,
                    "company_name": contact.company.name,
                    "invite_url": login_url,
                    "telegram_url": telegram_url,
                },
                to=[clean_email],
                channel="transactional",
                language=target_language,
            )
            email_sent = True
        except Exception as exc:
            logger.warning("Failed to send portal invitation email to %s: %s", clean_email, exc)
            return None, "EMAIL_DELIVERY_FAILED"

    # Фиксируем дату приглашения
    contact.invited_at = timezone.now()
    update_fields = ["invited_at"]
    if language and language in ("ru", "uz", "en") and contact.language != language:
        contact.language = language
        update_fields.append("language")
    contact.save(update_fields=update_fields)

    logger.info(
        "Contact %s invited to portal via %s by %s",
        contact.id,
        effective_channel,
        actor or "system",
    )

    try:
        from integration.services.webhooks import build_actor, emit_invite_sent

        actor_dict = build_actor(
            user=actor if hasattr(actor, "id") else None,
            name=str(actor) if isinstance(actor, str) else None,
        )
        channels_list = ["telegram", "email"] if effective_channel == "both" else [effective_channel]
        emit_invite_sent(contact=contact, channels=channels_list, actor=actor_dict)
    except Exception as exc:
        logger.warning("Failed to emit invite.sent webhook for contact %s: %s", contact.id, exc)

    return {
        "ok": True,
        "contact_id": contact.id,
        "channel": effective_channel,
        "email_sent": email_sent,
        "invited_at": contact.invited_at.isoformat(),
    }, None
