"""Код акцепта КП для контакта портала (FIX-22, контракт `POST /quotes/{id}/request-code`; FIX-60a, Q-FIX22-1/-6).

Код выпускает `crm.services.public_page.issue_acceptance_code` (6 цифр, 15 минут, 5 попыток, один активный код на КП,
в базе только хеш) — тот же сервис, что у публичной страницы КП; код привязан к контакту сессии, погасить его другим
контактом компании нельзя (`verify_code_and_accept(contact=)`). Здесь — выбор канала и маскирование адреса.

Канал: Telegram — если у контакта есть `telegram_user_id` и он сопоставлен с контактом CRM (`CrmContactMapping`, а компания
— с клиентом CRM): ERP выпускает событие `quote.acceptance_code_requested`, код доставляет бот CRM (бот принадлежит CRM, из
ERP в Telegram никто не пишет). Иначе — e-mail контакта через `EmailLog`. Нет ни того ни другого — `ContactChannelRequired`
(422 `CONTACT_CHANNEL_REQUIRED`). Код в событии — секрет: в журнал доставки он не попадает (`integration.services.webhooks`).
"""

from __future__ import annotations

import logging

from django.utils import timezone

from crm.services.public_page import CODE_TTL_MINUTES, issue_acceptance_code

logger = logging.getLogger(__name__)


class ContactChannelRequired(Exception):
    """У контакта нет канала, по которому можно отправить код."""


def mask_email(email: str) -> str:
    """`i***@example.com`: первая буква локальной части и домен целиком."""
    local, _, domain = email.partition("@")
    return f"{local[:1]}***@{domain}"


def mask_telegram(contact) -> str:
    """`@u***` по имени пользователя, а без него — слово `Telegram`."""
    username = (contact.telegram_username or "").lstrip("@")
    return f"@{username[:1]}***" if username else "Telegram"


def _emit_code_event(quote, contact, code: str) -> bool:
    """Событие кода акцепта для бота CRM; `False` — событие не выпущено (контакт или клиент не сопоставлены, сбой)."""
    from integration.services.webhooks import emit_quote_acceptance_code_requested
    from sales.models.acceptance import QuoteAcceptanceCode

    # Срок — у только что выпущенного кода (тот же момент, что проверяет акцепт), а не пересчитанный заново.
    expires_at = (
        QuoteAcceptanceCode.objects.filter(quote=quote, contact=contact, consumed_at__isnull=True)
        .order_by("-created_at")
        .values_list("expires_at", flat=True)
        .first()
    ) or timezone.now() + timezone.timedelta(minutes=CODE_TTL_MINUTES)
    try:
        return emit_quote_acceptance_code_requested(quote, contact, code, expires_at) is not None
    except (
        Exception
    ) as exc:  # noqa: BLE001 — сбой журнала или кэша не должен оставить клиента без кода: откат на письмо
        # В тексте исключения кода нет, но пишем только класс: тело события не должно попасть в лог.
        logger.warning("Acceptance-code event was not emitted for quote %s: %s", quote.pk, type(exc).__name__)
        return False


def request_acceptance_code(quote, contact, request_ip: str = "") -> dict:
    """Выпустить код для контакта сессии и отправить. Возвращает тело `AcceptanceCodeSent`."""
    email = (contact.email or "").strip()
    expires_in = CODE_TTL_MINUTES * 60

    if contact.telegram_user_id:
        emitted = []

        def send(code: str) -> None:
            emitted.append(_emit_code_event(quote, contact, code))

        issue_acceptance_code(quote, request_ip, contact=contact, send=send)
        if emitted and emitted[0]:
            return {"channel": "telegram", "sent_to": mask_telegram(contact), "expires_in": expires_in}
        # Событие не ушло (контакт не сопоставлен с CRM, сбой): откат на e-mail, если он есть.

    if not email:
        raise ContactChannelRequired
    issue_acceptance_code(quote, request_ip, contact=contact)
    return {"channel": "email", "sent_to": mask_email(email), "expires_in": expires_in}
