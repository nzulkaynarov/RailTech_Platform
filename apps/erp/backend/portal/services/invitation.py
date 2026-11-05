"""Portal Invitation service (CONTRACTS §4, M2-ERP-02).

Приглашение контакта клиента в Cabinet. Письмо ERP рендерит сама и передаёт почтовому сервису CRM (`send_templated_email` →
`EmailLog` QUEUED → событие `erp.mail.requested`, W18A-P1; синхронный сбой — только передача письма). Telegram-бот
принадлежит CRM, ERP в Telegram не пишет (CONVENTIONS.md §11), поэтому канал `telegram` — это событие шины
`invite.requested` (D1-9, Q-FIX23-1): бот CRM присылает контакту сообщение с кнопкой «Открыть кабинет» (Mini App, вход по
Telegram-аккаунту контакта; ссылок и токенов в событии нет). Событие уходит только контакту с привязанным
`telegram_user_id` и сопоставлением с контактом CRM; иначе — `CONTACT_TELEGRAM_REQUIRED`, а не молчаливый успех
(FIX-23, P-17). `sent_via` и событие `invite.sent` называют только письмо, по которому приглашение действительно ушло;
`telegram` в `sent_via` значит «передано боту», итог доставки видит CRM.
Рабочая ссылка входа уходит только клиенту, в письме; сотруднику, API и журналу отдаются факт
отправки и канал (FIX-14, P-11).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from django.db import transaction
from django.utils import timezone
from parties.models import Contact
from portal.exceptions import PortalDeliveryFailed, PortalValidationError
from portal.models import MagicLinkToken
from portal.services.access import company_has_cabinet_access, company_in_circulation, company_roles
from portal.services.login_code import INVITE_LINK_TTL, issue_login, reset_address_failures
from portal.services.magic_link import build_login_url
from portal.services.mail_context import responsible_manager_email
from rest_framework.exceptions import PermissionDenied

from notifications.emails import send_templated_email

logger = logging.getLogger(__name__)


#: Каналы, по которым ERP доставляет приглашение сама (приглашение коллеги клиентом из Cabinet — только письмо:
#: Telegram коллеги ERP не знает, ссылку на бот он получит от менеджера).
DELIVERABLE_CHANNELS = ("email",)
EMAIL, TELEGRAM = "email", "telegram"
_CHANNELS = (EMAIL, TELEGRAM, "both")


@dataclass(frozen=True)
class InviteOutcome:
    """Итог приглашения: каналы, по которым оно ушло, и причина по каждому, что не ушёл."""

    contact: Contact
    sent_via: Tuple[str, ...]
    errors: Dict[str, str]
    #: Код главной причины, если не ушло ни одним каналом; иначе `None`.
    error: Optional[str]
    #: Ключ письма в почтовом сервисе CRM (`erp:email_log:<id>`, B-MAIL-1): по нему CRM показывает итог доставки.
    email_request_key: Optional[str] = None


def _mark_invited(contact: Contact, actor, language: Optional[str], *, email_sent: bool) -> None:
    """Дата приглашения и событие шины `invite.sent` — одна транзакция и только после того, как письмо ушло.

    Telegram-приглашение (`invite.requested`) публикует вызывающий в этой же транзакции; `invite.sent` — только за письмо.
    Сбой публикации откатывает отметку (письмо уже у клиента, повторное приглашение безопасно).
    """
    from integration.services import events

    update_fields = ["invited_at"]
    with transaction.atomic():
        contact.invited_at = timezone.now()
        if language and language in ("ru", "uz", "en") and contact.language != language:
            contact.language = language
            update_fields.append("language")
        contact.save(update_fields=update_fields)
        if email_sent:
            events.publish_invite_sent(
                contact=contact,
                channels=["email"],
                actor=events.build_actor(
                    user=actor if hasattr(actor, "id") else None,
                    name=str(actor) if isinstance(actor, str) else None,
                ),
            )


def _send_email(
    contact: Contact, clean_email: str, language: Optional[str], actor=None
) -> Tuple[Optional[str], Optional[str]]:
    """Письмо-приглашение с новыми ссылкой и кодом входа: (код ошибки или `None`, ключ письма в почте CRM)."""
    # Гасим только прежние приглашения: ссылка входа, запрошенная клиентом, остаётся рабочей.
    # Ссылка и код приглашения действительны 24 часа; в базе — только хеши (B-MAIL-1).
    issued = issue_login(contact, MagicLinkToken.PURPOSE_INVITE, INVITE_LINK_TTL)
    reset_address_failures(clean_email)
    login_url = build_login_url(issued.raw_token)
    reply_to = responsible_manager_email(contact.company_id, actor)

    try:
        log = send_templated_email(
            "portal_invitation",
            context={
                "contact_name": contact.name,
                "company_name": contact.company.name,
                "invite_url": login_url,
                "login_code": issued.code,
                # Текст письма по роли: партнёр получает не клиентские разделы, а «Мои товары» (ADR-0022).
                "portal_role": "client" if "client" in company_roles(contact.company_id) else "partner",
            },
            to=[clean_email],
            channel="transactional",
            language=language or contact.language or "ru",
            reply_to=[reply_to] if reply_to else None,
            redact=(issued.code,),
        )
    except Exception as exc:  # noqa: BLE001 — письмо не передано почтовому сервису CRM: «отправлено» писать нельзя
        logger.warning("Failed to send portal invitation email to contact %s: %s", contact.pk, exc)
        return "EMAIL_DELIVERY_FAILED", None
    return None, f"erp:email_log:{log.pk}"


def _request_telegram(contact: Contact, actor) -> Optional[str]:
    """Событие `invite.requested` для бота CRM; `None` — передано боту, иначе код ошибки (у контакта нет Telegram в CRM)."""
    from integration.services import events

    with transaction.atomic():
        event = events.publish_invite_requested(
            contact,
            actor=events.build_actor(
                user=actor if hasattr(actor, "id") else None,
                name=str(actor) if isinstance(actor, str) else None,
            ),
        )
    return None if event is not None else "CONTACT_TELEGRAM_REQUIRED"


def invite_contact(
    contact: Contact,
    actor=None,
    channel: Optional[str] = None,
    language: Optional[str] = None,
) -> InviteOutcome:
    """Пригласить контакт клиента в личный кабинет выбранными каналами (D1-9).

    Каналы: `email`, `telegram`, `both`; по умолчанию — `contact.preferred_channel`. `both` пробует оба: приглашение
    считается ушедшим, если ушло хотя бы по одному (причина второго — в `errors`). Не ушло никуда — `error` с кодом
    причины: `CONTACT_EMAIL_REQUIRED`, `CONTACT_TELEGRAM_REQUIRED`, `EMAIL_DELIVERY_FAILED`, `CONTACT_CHANNEL_REQUIRED`
    (`both` без обоих адресов), `INVALID_CHANNEL`, `CONTACT_WITHOUT_COMPANY`, `COMPANY_ARCHIVED`, `COMPANY_NOT_CLIENT` (в кабинет входят клиенты и поставщики с отношением, `portal/services/access.py`; имя кода прежнее), `CONTACT_ARCHIVED`.
    """

    def failed(code: str) -> InviteOutcome:
        return InviteOutcome(contact, (), {}, code)

    if not contact.company:
        return failed("CONTACT_WITHOUT_COMPANY")
    if not company_in_circulation(contact.company_id):
        return failed("COMPANY_ARCHIVED")
    if not company_has_cabinet_access(contact.company_id):
        return failed("COMPANY_NOT_CLIENT")  # кабинет закрыт: не клиент и нет действующего отношения — войти не сможет
    if contact.is_archived:
        return failed("CONTACT_ARCHIVED")  # контакт удалён в CRM: в Cabinet не приглашается

    effective = channel or contact.preferred_channel or EMAIL
    if effective not in _CHANNELS:
        return failed("INVALID_CHANNEL")
    wanted = (EMAIL, TELEGRAM) if effective == "both" else (effective,)

    sent: List[str] = []
    errors: Dict[str, str] = {}
    email_key: Optional[str] = None
    clean_email = (contact.email or "").strip().lower()
    if EMAIL in wanted:
        if not clean_email:
            errors[EMAIL] = "CONTACT_EMAIL_REQUIRED"
        else:
            code, email_key = _send_email(contact, clean_email, language, actor)
            if code:
                errors[EMAIL] = code
            else:
                sent.append(EMAIL)
    if TELEGRAM in wanted:
        code = _request_telegram(contact, actor)
        if code:
            errors[TELEGRAM] = code
        else:
            sent.append(TELEGRAM)

    if not sent:
        main = errors[wanted[0]] if len(wanted) == 1 else "CONTACT_CHANNEL_REQUIRED"
        if len(wanted) > 1 and set(errors.values()) == {"EMAIL_DELIVERY_FAILED", "CONTACT_TELEGRAM_REQUIRED"}:
            main = "EMAIL_DELIVERY_FAILED"  # адрес есть, но почта не отработала — это важнее отсутствия Telegram
        return InviteOutcome(contact, (), errors, main)

    _mark_invited(contact, actor, language, email_sent=EMAIL in sent)
    logger.info("Contact %s invited to portal via %s by %s", contact.id, ",".join(sent), actor or "system")
    return InviteOutcome(contact, tuple(sent), errors, None, email_key)


def invite_contact_to_portal(
    contact: Contact,
    actor=None,
    channel: Optional[str] = None,
    language: Optional[str] = None,
) -> Tuple[Optional[dict], Optional[str]]:
    """Пригласить контакт клиента в личный кабинет (staff-эндпоинт). Возвращает (result, None) или (None, error_code).

    Обёртка над `invite_contact` с прежней формой ответа: `channel` — первый ушедший канал, `email_sent` — ушло ли письмо.
    """
    outcome = invite_contact(contact, actor=actor, channel=channel, language=language)
    if outcome.error:
        return None, outcome.error
    return {
        "ok": True,
        "contact_id": contact.id,
        "channel": outcome.sent_via[0],
        "email_sent": EMAIL in outcome.sent_via,
        "invited_at": contact.invited_at.isoformat(),
    }, None


def invite_team_member(company, inviter, data: dict) -> Contact:
    """`POST /team/invite`: завести коллегу в компании и отправить ему приглашение; вернуть контакта.

    Порядок проверок: каналы (`INVALID_CHANNEL` — доставляется только email) → адрес для письма
    (`CONTACT_EMAIL_REQUIRED`) → дубль в компании (`TEAM_MEMBER_EXISTS`). Контакт остаётся, только если письмо ушло:
    при сбое доставки он удаляется (повторить можно сразу), клиенту — 503, а не «отправлено».
    """
    if not company_has_cabinet_access(company.pk):
        # Сессия такой компании не живёт (PortalAuthentication), сюда доходят только прямым вызовом: коллега не заводится.
        raise PermissionDenied("FORBIDDEN")
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
