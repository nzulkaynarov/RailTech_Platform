"""Telegram WebApp initData validation & session issuance (CONTRACTS §4, M2-ERP-01)."""

import hashlib
import hmac
import json
import logging
import time
import urllib.parse
from typing import Tuple

from django.conf import settings
from parties.models import Contact, active_contact_q
from portal.models import PortalSession
from portal.services.access import company_in_circulation
from portal.services.tokens import issue_portal_session
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied

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

    # Проверка подписи HMAC-SHA256 — всегда: без токена бота вход через Mini App закрыт и в DEBUG
    # (иначе на стенде входит кто угодно под любым telegram_user_id; FIX-02, аудит P-2).
    if not token:
        logger.error("TELEGRAM_BOT_TOKEN is not configured — Mini App sign-in is disabled")
        raise AuthenticationFailed("INVALID_INIT_DATA")
    check_items = sorted([(k, v) for k, v in parsed_items if k != "hash"], key=lambda x: x[0])
    data_check_string = "\n".join(f"{k}={v}" for k, v in check_items)

    secret_key = hmac.new(b"WebAppData", token.encode("utf-8"), hashlib.sha256).digest()
    calculated_hash = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(calculated_hash, received_hash):
        logger.warning("init_data signature mismatch")
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

    # Только подписанный telegram_user_id: username меняется и переназначается, по нему не входят (FIX-14, P-11).
    contact = (
        Contact.objects.filter(active_contact_q(), telegram_user_id=telegram_user_id).select_related("company").first()
    )

    if not contact or not contact.company:
        logger.info("No contact found for telegram_user_id=%s", telegram_user_id)
        raise AuthenticationFailed("UNAUTHORIZED")

    if not company_in_circulation(contact.company_id):
        logger.info("Telegram sign-in rejected: company of contact %s is archived", contact.pk)
        raise PermissionDenied("FORBIDDEN")

    return issue_portal_session(contact, "telegram", ip_address=ip_address, user_agent=user_agent)
