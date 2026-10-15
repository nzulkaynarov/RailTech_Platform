"""Telegram WebApp initData validation & session issuance (CONTRACTS §4, M2-ERP-01)."""

import hashlib
import hmac
import json
import logging
import secrets
import time
import urllib.parse
from typing import Tuple

from django.conf import settings
from django.utils import timezone
from parties.models import Contact
from portal.models import PortalSession
from rest_framework.exceptions import AuthenticationFailed

logger = logging.getLogger(__name__)


def validate_and_parse_init_data(init_data: str, bot_token: str = "") -> dict:
    """Проверяет подпись initData токеном бота (HMAC-SHA-256) и срок <= 5 минут.

    Формат Telegram WebApp:
      - secret_key = HMAC_SHA256("WebAppData", bot_token)
      - data_check_string = key1=val1\nkey2=val2 (все поля кроме hash, отсортированные по алфавиту)
      - hash = HMAC_SHA256(data_check_string, secret_key).hexdigest()
      - auth_date <= 300 секунд
    """
    token = bot_token or getattr(settings, "TELEGRAM_BOT_TOKEN", "")

    try:
        parsed_items = urllib.parse.parse_qsl(init_data, keep_blank_values=True)
    except Exception as exc:
        logger.warning("Failed to parse init_data query string: %s", exc)
        raise AuthenticationFailed("INVALID_INIT_DATA") from exc

    data_dict = dict(parsed_items)
    received_hash = data_dict.get("hash")

    if not received_hash or not data_dict.get("auth_date"):
        raise AuthenticationFailed("INVALID_INIT_DATA")

    # Проверка auth_date (срок <= 5 минут)
    try:
        auth_date = int(data_dict["auth_date"])
        if abs(time.time() - auth_date) > 300:
            logger.info("init_data auth_date expired: %s vs now %s", auth_date, int(time.time()))
            raise AuthenticationFailed("INVALID_INIT_DATA")
    except (ValueError, TypeError) as exc:
        raise AuthenticationFailed("INVALID_INIT_DATA") from exc

    # Проверка подписи HMAC-SHA256
    if token:
        check_items = sorted([(k, v) for k, v in parsed_items if k != "hash"], key=lambda x: x[0])
        data_check_string = "\n".join(f"{k}={v}" for k, v in check_items)

        secret_key = hmac.new(b"WebAppData", token.encode("utf-8"), hashlib.sha256).digest()
        calculated_hash = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()

        if not hmac.compare_digest(calculated_hash, received_hash):
            logger.warning("init_data signature mismatch")
            raise AuthenticationFailed("INVALID_INIT_DATA")
    elif not settings.DEBUG:
        logger.error("TELEGRAM_BOT_TOKEN is not configured in production")
        raise AuthenticationFailed("INVALID_INIT_DATA")

    # Извлечение данных пользователя
    user_str = data_dict.get("user")
    if not user_str:
        raise AuthenticationFailed("INVALID_INIT_DATA")

    try:
        user_data = json.loads(user_str)
    except Exception as exc:
        raise AuthenticationFailed("INVALID_INIT_DATA") from exc

    return user_data


def authenticate_telegram_user(
    init_data: str,
    ip_address: str = None,
    user_agent: str = "",
    bot_token: str = "",
) -> Tuple[PortalSession, str]:
    """Аутентифицирует пользователя Telegram, ищет Contact и создаёт PortalSession."""
    user_data = validate_and_parse_init_data(init_data, bot_token=bot_token)
    telegram_user_id = user_data.get("id")

    if not telegram_user_id:
        raise AuthenticationFailed("INVALID_INIT_DATA")

    contact = Contact.objects.filter(telegram_user_id=telegram_user_id).select_related("company").first()

    # Fallback на telegram_username, если ID еще не привязан
    if not contact and user_data.get("username"):
        contact = (
            Contact.objects.filter(telegram_username__iexact=user_data["username"]).select_related("company").first()
        )
        if contact and not contact.telegram_user_id:
            contact.telegram_user_id = telegram_user_id
            contact.save(update_fields=["telegram_user_id"])

    if not contact or not contact.company:
        logger.info("No contact found for telegram_user_id=%s", telegram_user_id)
        raise AuthenticationFailed("UNAUTHORIZED")

    # Генерация сессии
    token = secrets.token_hex(32)
    max_age_days = getattr(settings, "PORTAL_SESSION_MAX_AGE_DAYS", 14)
    expires_at = timezone.now() + timezone.timedelta(days=max_age_days)

    session = PortalSession.objects.create(
        token=token,
        contact=contact,
        company=contact.company,
        auth_method="telegram",
        ip_address=ip_address,
        user_agent=user_agent,
        expires_at=expires_at,
    )

    contact.last_login_at = timezone.now()
    contact.save(update_fields=["last_login_at"])

    return session, token
