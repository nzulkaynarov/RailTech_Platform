"""Portal Invitation service (CONTRACTS §4, M2-ERP-02).

Приглашение контакта клиента в Cabinet. Реально доставляется только письмо (`send_templated_email` → `EmailLog`):
Telegram-бот принадлежит CRM, ERP в Telegram не пишет (apps/erp/CLAUDE.md §11), поэтому канал `telegram` не
«отправляется» молча, а отвечает `INVALID_CHANNEL` (FIX-23, P-17; QUESTIONS Q-FIX23-1). Результат и событие
`invite.sent` называют только те каналы, по которым приглашение действительно ушло.
Рабочая ссылка входа уходит только клиенту, в письме; сотруднику, API и журналу отдаются факт
отправки и канал (FIX-14, P-11).
"""

from __future__ import annotations

import logging
from typing import Optional, Tuple

from django.conf import settings
from django.utils import timezone
from parties.models import Contact
from portal.exceptions import PortalDeliveryFailed, PortalValidationError
from portal.models import MagicLinkToken
from portal.services.access import company_in_circulation
from portal.services.magic_link import build_login_url
from portal.services.tokens import generate_token, hash_token

from notifications.emails import send_templated_email

logger = logging.getLogger(__name__)


#: Каналы, по которым ERP умеет доставить приглашение сама.
DELIVERABLE_CHANNELS = ("email",)


def invite_contact_to_portal(
    contact: Contact,
    actor=None,
    channel: Optional[str] = None,
    language: Optional[str] = None,
) -> Tuple[Optional[dict], Optional[str]]:
    """Пригласить контакт клиента в личный кабинет.

    Возвращает (result, None) или (None, error_code).
    Каналы: 'email', 'telegram', 'both'. По умолчанию берется `contact.preferred_channel`.
    Доставляется только письмо: `telegram` — `INVALID_CHANNEL`; `both` уходит письмом, и `channel` в результате
    называет то, что реально ушло (`email`).
    """
    if not contact.company:
        return None, "CONTACT_WITHOUT_COMPANY"
    if not company_in_circulation(contact.company_id):
        return None, "COMPANY_ARCHIVED"

    effective_channel = channel or contact.preferred_channel or "email"
    if effective_channel not in ("email", "telegram", "both"):
        return None, "INVALID_CHANNEL"
    if effective_channel == "telegram":
        return None, "INVALID_CHANNEL"  # путь к боту CRM для нового приглашённого контакта в ERP отсутствует

    clean_email = (contact.email or "").strip().lower()
    if not clean_email:
        return None, "CONTACT_EMAIL_REQUIRED"

    # Гасим только прежние приглашения: ссылка входа, запрошенная клиентом, остаётся рабочей.
    MagicLinkToken.objects.filter(contact=contact, purpose=MagicLinkToken.PURPOSE_INVITE, used_at__isnull=True).update(
        used_at=timezone.now()
    )

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
            language=language or contact.language or "ru",
        )
    except Exception as exc:  # noqa: BLE001 — любой сбой транспорта: письмо не ушло, «отправлено» писать нельзя
        logger.warning("Failed to send portal invitation email to %s: %s", clean_email, exc)
        return None, "EMAIL_DELIVERY_FAILED"

    # Фиксируем дату приглашения: она ставится только после того, как письмо ушло
    contact.invited_at = timezone.now()
    update_fields = ["invited_at"]
    if language and language in ("ru", "uz", "en") and contact.language != language:
        contact.language = language
        update_fields.append("language")
    contact.save(update_fields=update_fields)

    logger.info("Contact %s invited to portal via email by %s", contact.id, actor or "system")

    try:
        from integration.services.webhooks import build_actor, emit_invite_sent

        actor_dict = build_actor(
            user=actor if hasattr(actor, "id") else None,
            name=str(actor) if isinstance(actor, str) else None,
        )
        emit_invite_sent(contact=contact, channels=["email"], actor=actor_dict)
    except Exception as exc:  # noqa: BLE001 — событие не должно ронять уже отправленное приглашение
        logger.warning("Failed to emit invite.sent webhook for contact %s: %s", contact.id, exc)

    return {
        "ok": True,
        "contact_id": contact.id,
        "channel": "email",
        "email_sent": True,
        "invited_at": contact.invited_at.isoformat(),
    }, None


def invite_team_member(company, inviter, data: dict) -> Contact:
    """`POST /team/invite`: завести коллегу в компании и отправить ему приглашение; вернуть контакта.

    Порядок проверок: каналы (`INVALID_CHANNEL` — доставляется только email) → адрес для письма
    (`CONTACT_EMAIL_REQUIRED`) → дубль в компании (`TEAM_MEMBER_EXISTS`). Контакт остаётся, только если письмо ушло:
    при сбое доставки он удаляется (повторить можно сразу), клиенту — 503, а не «отправлено».
    """
    channels = list(dict.fromkeys(data["channels"]))
    if set(channels) - set(DELIVERABLE_CHANNELS):
        raise PortalValidationError("INVALID_CHANNEL")
    email = (data.get("email") or "").strip().lower()
    phone = (data.get("phone") or "").strip()
    if not email:
        raise PortalValidationError("CONTACT_EMAIL_REQUIRED")

    existing = Contact.objects.filter(company=company)
    if existing.filter(email__iexact=email).exists() or (phone and existing.filter(phone=phone).exists()):
        raise PortalValidationError("TEAM_MEMBER_EXISTS")

    contact = Contact.objects.create(
        company=company,
        name=data["name"].strip(),
        email=email,
        phone=phone,
        language=data.get("language", "ru"),
        can_act=data.get("can_act", False),
        preferred_channel="email",
        is_primary=False,
    )
    _result, error = invite_contact_to_portal(
        contact=contact, actor=inviter, channel="email", language=contact.language
    )
    if error:
        contact.delete()  # письмо не ушло — коллеги в команде нет; EmailLog о сбое остаётся
        if error in ("INVALID_CHANNEL", "CONTACT_EMAIL_REQUIRED"):
            raise PortalValidationError(error)
        raise PortalDeliveryFailed()
    contact.refresh_from_db()
    return contact
