"""Код акцепта КП для контакта портала (FIX-22, контракт `POST /quotes/{id}/request-code`; FIX-60a, Q-FIX22-1/-6).

Код выпускает `crm.services.public_page.issue_acceptance_code` (6 цифр, 15 минут, 5 попыток, один активный код на КП,
в базе только хеш) — тот же сервис, что у публичной страницы КП; код привязан к контакту сессии, погасить его другим
контактом компании нельзя (`verify_code_and_accept(contact=)`). Здесь — выбор канала и маскирование адреса.

Канал: Telegram — если у контакта есть `telegram_user_id` и он сопоставлен с контактом CRM (`CrmContactMapping`, а компания
— с клиентом CRM): ERP публикует на шину rt_bus событие `quote.acceptance_code_requested`, код доставляет бот CRM (бот принадлежит CRM, из
ERP в Telegram никто не пишет). Иначе — e-mail контакта через `EmailLog`. Нет ни того ни другого — `ContactChannelRequired`
(422 `CONTACT_CHANNEL_REQUIRED`). Код в событии — секрет: в outbox шины он лежит маской `***`, значение — в кэше на 20 минут
(`rt_bus.django.stash.DjangoCacheStash`). Выпуск кода и событие — одна транзакция: сбой публикации откатывает выпуск кода.
"""

from __future__ import annotations

import logging

from django.db import transaction
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
    """Событие кода акцепта для бота CRM; `False` — событие не выпущено (контакт или клиент не сопоставлены).

    Сбой публикации (шина, кэш секрета, схема) — исключение наружу: выпуск кода откатывается вместе с ним.
    """
    from integration.services import events
    from sales.models.acceptance import QuoteAcceptanceCode

    # Срок — у только что выпущенного кода (тот же момент, что проверяет акцепт), а не пересчитанный заново.
    expires_at = (
        QuoteAcceptanceCode.objects.filter(quote=quote, contact=contact, consumed_at__isnull=True)
        .order_by("-created_at")
        .values_list("expires_at", flat=True)
        .first()
    ) or timezone.now() + timezone.timedelta(minutes=CODE_TTL_MINUTES)
    return events.publish_quote_acceptance_code_requested(quote, contact, code, expires_at) is not None


def _telegram_deliverable(contact) -> bool:
    """Код можно отдать боту CRM: у контакта есть Telegram и сопоставление с контактом CRM, компания сопоставлена с клиентом."""
    from integration.models import CrmClientMapping, CrmContactMapping

    return bool(
        contact.telegram_user_id
        and CrmContactMapping.objects.filter(contact=contact).exists()
        and CrmClientMapping.objects.filter(company_id=contact.company_id).exists()
    )


def request_acceptance_code(quote, contact, request_ip: str = "") -> dict:
    """Выпустить код для контакта сессии и отправить. Возвращает тело `AcceptanceCodeSent`.

    Канал выбирается ДО выпуска: контакт без канала получает `ContactChannelRequired`, и активный код коллеги не гасится.
    """
    email = (contact.email or "").strip()
    expires_in = CODE_TTL_MINUTES * 60
    telegram = _telegram_deliverable(contact)
    if not telegram and not email:
        raise ContactChannelRequired

    if telegram:
        emitted = []

        def send(code: str) -> None:
            emitted.append(_emit_code_event(quote, contact, code))

        with transaction.atomic():  # код и событие шины — одна транзакция
            issue_acceptance_code(quote, request_ip, contact=contact, send=send)
        if emitted and emitted[0]:
            return {"channel": "telegram", "sent_to": mask_telegram(contact), "expires_in": expires_in}
        # Событие не выпущено (контакт или клиент не сопоставлены с CRM): откат на e-mail, если он есть.
        if not email:
            _drop_unsent_code(quote, contact)
            raise ContactChannelRequired

    issue_acceptance_code(quote, request_ip, contact=contact)
    return {"channel": "email", "sent_to": mask_email(email), "expires_in": expires_in}


def _drop_unsent_code(quote, contact) -> None:
    """Код, который не удалось отправить ни одним каналом, не остаётся активным."""
    from sales.models.acceptance import QuoteAcceptanceCode

    QuoteAcceptanceCode.objects.filter(quote=quote, contact=contact, consumed_at__isnull=True).delete()
