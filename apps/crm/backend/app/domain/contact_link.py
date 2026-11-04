"""Токен привязки Telegram контактом (NOTIFY-1, ADR-0023 п. 3): разбор и проверка подписи и срока.

Выпускает ERP из сессии контакта в кабинете (`apps/erp/backend/portal/services/telegram_link.py`,
формат — контракт `POST /me/telegram-link` в `packages/contracts/openapi/erp-portal.yaml`); бот
получает его параметром `/start`:

    "tg_" + base64url(без "=")( data[21] + mac[15] )  → 51 символ
    data = версия(1) · язык(1: ru/uz/en = 0/1/2) · crm_contact_id(6) · срок(4) · nonce(9)
    mac  = HMAC-SHA256(ключ, data)[:15]  (120 бит)
    ключ = HMAC-SHA256(секрет пары шины erp → crm, "rt-telegram-link/v1")

Секрет пары CRM считает сама из секрета вебхуков сопряжения (ADR-0014 L12) — по шине он не ходит.
Пробуются все действующие секреты (ротация без простоя). Сравнение подписи — `hmac.compare_digest`
(за постоянное время). Одноразовость — не здесь: nonce гасит сервис в базе (`telegram_link_nonces`,
уникальность). Чистые функции без I/O.
"""

import base64
import binascii
import hashlib
import hmac
import re
import struct
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

PREFIX: Final = "tg_"
VERSION: Final = 1
KEY_LABEL: Final = b"rt-telegram-link/v1"
MAC_BYTES: Final = 15
_DATA: Final = struct.Struct(">BB6sI9s")
_TOKEN: Final = re.compile(r"^tg_[A-Za-z0-9_-]{48}$")
_LANGUAGES: Final = ("ru", "uz", "en")


@dataclass(frozen=True, slots=True)
class ContactLink:
    crm_contact_id: int
    language: str
    expires_at: datetime
    nonce: str  # hex, 18 символов: ключ одноразовости


_ANY_TOKEN: Final = re.compile(r"tg_[A-Za-z0-9_-]{48}")


def mask_tokens(text: str) -> str:
    """Текст для хранения и показа менеджеру: токены привязки заменены на `tg_***` (непогашенный
    токен в переписке позволил бы сотруднику привязать к контакту свой Telegram)."""
    return _ANY_TOKEN.sub("tg_***", text)


def looks_like(raw: str | None) -> bool:
    """Похоже ли на токен привязки (по форме, без проверки подписи) — для разбора `/start`."""
    return bool(_TOKEN.fullmatch((raw or "").strip()))


def link_key(pair_secret: str) -> bytes:
    return hmac.new(pair_secret.encode("utf-8"), KEY_LABEL, hashlib.sha256).digest()


def verify(raw: str, pair_secrets: Iterable[str], now: datetime) -> ContactLink | None:
    """Токен, если форма, версия, подпись (любым действующим секретом) и срок верны; иначе `None`
    — без причины:
    вызывающий отвечает одним нейтральным отказом и не выдаёт, что именно не так."""
    text = (raw or "").strip()
    if not _TOKEN.fullmatch(text):
        return None
    try:
        blob = base64.urlsafe_b64decode(text[len(PREFIX) :])  # 48 символов — ровно 36 байт, без «=»
    except (binascii.Error, ValueError):
        return None
    if len(blob) != _DATA.size + MAC_BYTES:
        return None
    data, mac = blob[: _DATA.size], blob[_DATA.size :]
    signed = False
    for secret in pair_secrets:
        expected = hmac.new(link_key(secret), data, hashlib.sha256).digest()[:MAC_BYTES]
        signed = (
            hmac.compare_digest(expected, mac) or signed
        )  # без раннего выхода: время не зависит от секрета
    if not signed:
        return None
    version, language, contact, expires, nonce = _DATA.unpack(data)
    expires_at = datetime.fromtimestamp(expires, tz=UTC)
    contact_id = int.from_bytes(contact, "big")
    if version != VERSION or expires_at < now or contact_id <= 0:
        return None
    return ContactLink(
        contact_id, _LANGUAGES[language] if language < 3 else "ru", expires_at, nonce.hex()
    )
