"""Привязка Telegram самим контактом (NOTIFY-1, ADR-0023 п. 3): одноразовая ссылка бота, статус и отключение.

Telegram контакта принадлежит CRM (ADR-0015, один владелец у поля): ERP поле `Contact.telegram_user_id` только проецирует
из `crm.contact.*`. Поэтому ERP не привязывает и не отвязывает сама:

* **привязка** — ERP выпускает из сессии контакта ссылку `https://t.me/<бот>?start=<токен>`; бот CRM проверяет подпись и
  срок, гасит токен и привязывает Telegram к контакту без подтверждения менеджера, затем публикует `crm.contact.updated` с
  `telegram_user_id` — проекция ERP заполняется (`integration/services/crm_projections.py`), Mini App начинает входить;
* **отключение** — ERP публикует запрос `uz.railtech.erp.contact.telegram_unlink_requested.v1`, CRM отвязывает и публикует
  `crm.contact.updated` без `telegram_user_id`;
* **статус** — по проекции (`telegram_user_id`), Cabinet опрашивает его, пока открыт экран;
* **проверочное сообщение** — ERP публикует запрос `uz.railtech.erp.contact.telegram_test_requested.v1`, бот CRM пишет
  контакту; не чаще `TEST_INTERVAL` на контакт (кэш, атомарный `add`), иначе 429 с `Retry-After`.

Токен (формат — контракт `POST /me/telegram-link`; разбор — `apps/crm/backend/app/domain/contact_link.py`, тест-вектор в обеих
системах одинаковый). Параметр `start` Telegram — до 64 символов `[A-Za-z0-9_-]`, поэтому упаковка бинарная:

    "tg_" + base64url(без "=")( data[21] + mac[15] )                         → 3 + 48 = 51 символ
    data = версия(1) · язык(1: ru=0, uz=1, en=2) · crm_contact_id(6, big-endian) · срок(4, unix, big-endian) · nonce(9)
    mac  = HMAC-SHA256(ключ, data)[:15]  (120 бит)
    ключ = HMAC-SHA256(секрет пары шины erp → crm, "rt-telegram-link/v1")

Ключ производный, со своей меткой: он не совпадает ни с подписью шины, ни с ключом тела писем (`rt-mail/v1/content`), хотя
источник — тот же секрет пары (секрет по шине не ходит, CRM считает его сама, ADR-0014 L12). Префикс `tg_` не пересекается с
прежними параметрами `/start` (`web`, `deal_<id>`, `lead_<…>`). Одноразовость держит CRM (nonce в базе с уникальностью).

Токен в письмо не кладётся (решение NOTIFY-1): 15-минутная ссылка в письме почти всегда просрочена к прочтению, а письма
пересылают — в письмах ссылка на Профиль → «Уведомления», где токен выпускается из сессии.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import secrets
import struct
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone
from integration.models import CrmContactMapping
from parties.models import Contact
from portal.exceptions import PortalConflict, PortalUnavailable, PortalValidationError
from rest_framework.exceptions import Throttled

logger = logging.getLogger(__name__)

TOKEN_PREFIX = "tg_"
TOKEN_VERSION = 1
LINK_TTL = timedelta(minutes=15)
KEY_LABEL = b"rt-telegram-link/v1"
MAC_BYTES = 15
NONCE_BYTES = 9
#: Язык контакта в токене: бот здоровается на нём, хотя Telegram-аккаунт CRM видит впервые.
LANGUAGE_CODES = {"ru": 0, "uz": 1, "en": 2}
_DATA = struct.Struct(">BB6sI9s")  # версия, язык, crm_contact_id (48 бит), срок, nonce
_MAX_CONTACT_ID = (1 << 48) - 1

PUBLISHER, SUBSCRIBER = "erp", "crm"
#: Проверочное сообщение — не чаще раза в минуту на контакт (защита бота и человека от серии нажатий).
TEST_INTERVAL = timedelta(minutes=1)


@dataclass(frozen=True)
class TelegramLink:
    url: str
    expires_at: datetime


def link_key(pair_secret: str) -> bytes:
    """Ключ подписи ссылок: HMAC-SHA256(секрет пары erp → crm, "rt-telegram-link/v1")."""
    return hmac.new(pair_secret.encode("utf-8"), KEY_LABEL, hashlib.sha256).digest()


def issue_token(
    pair_secret: str, crm_contact_id: int, language: str, now: datetime, nonce: Optional[bytes] = None
) -> tuple[str, datetime]:
    """Параметр `start`: `tg_` + base64url(данные + усечённый HMAC). Возвращает (токен, срок)."""
    if not 0 < crm_contact_id <= _MAX_CONTACT_ID:
        raise ValueError("crm_contact_id вне 48 бит")
    nonce = secrets.token_bytes(NONCE_BYTES) if nonce is None else nonce
    if len(nonce) != NONCE_BYTES:
        raise ValueError("nonce — ровно 9 байт")
    expires_at = (now + LINK_TTL).replace(microsecond=0)
    data = _DATA.pack(
        TOKEN_VERSION,
        LANGUAGE_CODES.get(language, 0),
        crm_contact_id.to_bytes(6, "big"),
        int(expires_at.timestamp()),
        nonce,
    )
    mac = hmac.new(link_key(pair_secret), data, hashlib.sha256).digest()[:MAC_BYTES]
    body = base64.urlsafe_b64encode(data + mac).decode("ascii").rstrip("=")
    return TOKEN_PREFIX + body, expires_at


def _pair_secret() -> Optional[str]:
    from integration.bus import pair_secrets

    found = pair_secrets(PUBLISHER, SUBSCRIBER)
    return found[0] if found else None


def _bot_username() -> str:
    return (getattr(settings, "TELEGRAM_BOT_USERNAME", "") or "").strip().lstrip("@")


def _crm_contact_id(contact: Contact) -> Optional[int]:
    return CrmContactMapping.objects.filter(contact=contact).values_list("crm_contact_id", flat=True).first()


def telegram_status(contact: Contact) -> dict:
    """`TelegramStatus`: привязан ли (по проекции CRM) и можно ли выпустить ссылку (бот, сопряжение, сопоставление)."""
    available = bool(_bot_username()) and _crm_contact_id(contact) is not None and _pair_secret() is not None
    return {"linked": bool(contact.telegram_user_id), "available": available}


def issue_telegram_link(contact: Contact, now: Optional[datetime] = None) -> TelegramLink:
    """Ссылка привязки для контакта сессии. Нет сопоставления с CRM — 422 `CONTACT_NOT_IN_CRM`; нет бота или секрета пары —
    503 `TELEGRAM_LINK_UNAVAILABLE` (ни то ни другое не 500)."""
    crm_contact_id = _crm_contact_id(contact)
    if crm_contact_id is None:
        raise PortalValidationError("CONTACT_NOT_IN_CRM")
    bot, secret = _bot_username(), _pair_secret()
    if not bot or secret is None:
        logger.warning(
            "telegram_link: ссылку выпустить нельзя (бот задан: %s, секрет пары: %s)", bool(bot), bool(secret)
        )
        raise PortalUnavailable("TELEGRAM_LINK_UNAVAILABLE")
    token, expires_at = issue_token(secret, crm_contact_id, contact.language or "ru", now or timezone.now())
    logger.info("telegram_link: ссылка выпущена контакту #%s до %s", contact.pk, expires_at.isoformat())
    return TelegramLink(url=f"https://t.me/{bot}?start={token}", expires_at=expires_at)


def request_telegram_unlink(contact: Contact) -> dict:
    """Отключение Telegram: запрос в CRM через outbox в транзакции; Telegram не привязан — без события (повтор безопасен).

    Возвращает `TelegramStatus` на момент ответа: `linked` станет `false`, когда CRM опубликует `contact.updated`.
    """
    from integration.services import events

    if not contact.telegram_user_id:
        return telegram_status(contact)
    crm_contact_id = _crm_contact_id(contact)
    if crm_contact_id is None:
        raise PortalValidationError("CONTACT_NOT_IN_CRM")
    with transaction.atomic():
        event = events.publish_contact_telegram_unlink_requested(contact, crm_contact_id)
        if event is None:  # компания не сопоставлена клиенту CRM — запрос некому доставить
            raise PortalValidationError("CONTACT_NOT_IN_CRM")
    logger.info("telegram_link: контакт #%s попросил отключить Telegram", contact.pk)
    return telegram_status(contact)


def _test_key(contact: Contact) -> str:
    return f"portal:telegram-test:{contact.pk}"


def request_telegram_test(contact: Contact, now: Optional[datetime] = None) -> dict:
    """Проверочное сообщение в привязанный Telegram: запрос боту CRM через outbox.

    Не привязан — 409 `TELEGRAM_NOT_LINKED`; нет сопоставления с CRM — 422 `CONTACT_NOT_IN_CRM`; чаще раза в минуту — 429
    `TOO_MANY_REQUESTS` с `Retry-After` (DRF `Throttled`, код ставит `portal_exception_handler`). Отметка ставится атомарно
    (`cache.add`) до публикации и снимается, если публикация не удалась: параллельные нажатия дают одно сообщение.
    """
    from integration.services import events

    if not contact.telegram_user_id:
        raise PortalConflict("TELEGRAM_NOT_LINKED")
    crm_contact_id = _crm_contact_id(contact)
    if crm_contact_id is None:
        raise PortalValidationError("CONTACT_NOT_IN_CRM")
    moment = now or timezone.now()
    interval = int(TEST_INTERVAL.total_seconds())
    if not cache.add(_test_key(contact), moment.timestamp(), interval):
        sent_at = cache.get(_test_key(contact)) or moment.timestamp()
        raise Throttled(wait=max(1, int(interval - (moment.timestamp() - float(sent_at)))))
    published = False
    try:
        with transaction.atomic():
            event = events.publish_contact_telegram_test_requested(contact, crm_contact_id)
            if event is None:
                raise PortalValidationError("CONTACT_NOT_IN_CRM")
        published = True
    finally:
        if not published:  # сбой публикации не «съедает» минуту: повторить можно сразу
            cache.delete(_test_key(contact))
    logger.info("telegram_link: контакт #%s попросил проверочное сообщение", contact.pk)
    return telegram_status(contact)
