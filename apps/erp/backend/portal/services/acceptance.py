"""Код акцепта КП для контакта портала (FIX-22, контракт 0.2.0 `POST /quotes/{id}/request-code`).

Код выпускает `crm.services.public_page.issue_acceptance_code` (6 цифр, 15 минут, 5 попыток, один активный код на КП,
в базе только хеш) — тот же сервис, что у публичной страницы КП; здесь только выбор канала и маскирование адреса.

Канал: Telegram — если у контакта есть `telegram_user_id` и ERP явно настроена слать через бота
(`PORTAL_ACCEPT_CODE_TELEGRAM` + `TELEGRAM_BOT_TOKEN`); иначе e-mail контакта через `EmailLog`. Бот принадлежит CRM,
поэтому по умолчанию ERP в Telegram не пишет, а недоставленный Telegram откатывается на e-mail. Нет ни того ни
другого — `ContactChannelRequired` (422 `CONTACT_CHANNEL_REQUIRED`).
"""

from __future__ import annotations

import logging

import httpx
from django.conf import settings

from crm.services.public_page import CODE_TTL_MINUTES, issue_acceptance_code

logger = logging.getLogger(__name__)

TELEGRAM_API_TIMEOUT = 5.0

_TELEGRAM_TEXT = {
    "ru": "Код подтверждения КП {number}: {code}. Действует {minutes} мин. Никому не сообщайте код.",
    "en": "Quotation {number} confirmation code: {code}. Valid for {minutes} min. Do not share it.",
    "uz": "{number}-sonli TT tasdiqlash kodi: {code}. {minutes} daqiqa amal qiladi. Kodni hech kimga bermang.",
}


class ContactChannelRequired(Exception):
    """У контакта нет канала, по которому можно отправить код."""


def telegram_delivery_enabled() -> bool:
    return bool(getattr(settings, "PORTAL_ACCEPT_CODE_TELEGRAM", False) and getattr(settings, "TELEGRAM_BOT_TOKEN", ""))


def mask_email(email: str) -> str:
    """`i***@example.com`: первая буква локальной части и домен целиком."""
    local, _, domain = email.partition("@")
    return f"{local[:1]}***@{domain}"


def mask_telegram(contact) -> str:
    """`@u***` по имени пользователя, а без него — слово `Telegram`."""
    username = (contact.telegram_username or "").lstrip("@")
    return f"@{username[:1]}***" if username else "Telegram"


def send_text_via_bot(chat_id: int, text: str) -> bool:
    """Отправить сообщение в Telegram Bot API. Любая неудача — `False` (токен в журнал не попадает)."""
    url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        response = httpx.post(url, json={"chat_id": chat_id, "text": text}, timeout=TELEGRAM_API_TIMEOUT)
        return response.status_code == 200 and response.json().get("ok") is True
    except (httpx.HTTPError, ValueError) as exc:
        # В тексте httpx-исключения бывает URL с токеном бота — пишем только класс ошибки.
        logger.warning("Telegram acceptance-code delivery failed: %s", type(exc).__name__)
        return False


def _telegram_text(quote, contact, code: str) -> str:
    template = _TELEGRAM_TEXT.get(contact.language, _TELEGRAM_TEXT["ru"])
    return template.format(number=quote.number or f"Q-{quote.pk}", code=code, minutes=CODE_TTL_MINUTES)


def request_acceptance_code(quote, contact, request_ip: str = "") -> dict:
    """Выпустить код для контакта сессии и отправить. Возвращает тело `AcceptanceCodeSent`."""
    email = (contact.email or "").strip()
    expires_in = CODE_TTL_MINUTES * 60

    if contact.telegram_user_id and telegram_delivery_enabled():
        delivered = []

        def send(code: str) -> None:
            delivered.append(send_text_via_bot(contact.telegram_user_id, _telegram_text(quote, contact, code)))

        issue_acceptance_code(quote, request_ip, contact=contact, send=send)
        if delivered and delivered[0]:
            return {"channel": "telegram", "sent_to": mask_telegram(contact), "expires_in": expires_in}
        # Бот не доставил (пользователь не запускал бота, сбой сети): откат на e-mail, если он есть.

    if not email:
        raise ContactChannelRequired
    issue_acceptance_code(quote, request_ip, contact=contact)
    return {"channel": "email", "sent_to": mask_email(email), "expires_in": expires_in}
