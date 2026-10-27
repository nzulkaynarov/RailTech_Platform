"""Сброс пароля по ссылке (W15-H6): токен, срок, лимит и выбор канала. Чистые функции.

Токен одноразовый, живёт `TOKEN_TTL`, в БД лежит хеш. Ссылка уходит на почту (если коннектор
«Почта» настроен) или в Telegram (если привязан); нет ни того, ни другого — письма нет, а ответ
запроса одинаков для любой учётной записи (перечислять сотрудников нельзя).
"""

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta
from typing import Final, Literal

TOKEN_TTL: Final = timedelta(minutes=60)
# Не больше трёх ссылок в час на одну учётную запись: защита от заспамленной почты сотрудника.
MAX_REQUESTS_PER_HOUR: Final = 3
WINDOW: Final = timedelta(hours=1)

Channel = Literal["email", "telegram"]


def new_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def same_token(token: str, stored_hash: str) -> bool:
    return hmac.compare_digest(hash_token(token), stored_hash)


def delivery_channel(*, mail_ready: bool, telegram_ready: bool) -> Channel | None:
    """Почта главнее (письмо остаётся в журнале и в ящике), Telegram — запасной путь."""
    if mail_ready:
        return "email"
    if telegram_ready:
        return "telegram"
    return None


def rate_exceeded(recent_requests: int) -> bool:
    return recent_requests >= MAX_REQUESTS_PER_HOUR


def usable(expires_at: datetime, used_at: datetime | None, now: datetime) -> bool:
    return used_at is None and now < expires_at


def reset_link(platform_url: str, token: str) -> str:
    return f"{platform_url.rstrip('/')}/reset-password?token={token}"


TELEGRAM_TEXT: Final = {
    "ru": (
        "Сброс пароля в Платформе. Откройте ссылку и задайте новый пароль "
        "(действует час, один раз): {link}\nЕсли вы не просили сброс, ничего не делайте."
    ),
    "uz": (
        "Platformada parolni tiklash. Havolani oching va yangi parol oʻrnating "
        "(bir soat, bir marta): {link}\nAgar siz soʻramagan boʻlsangiz, hech narsa qilmang."
    ),
    "en": (
        "Password reset in the Platform. Open the link and set a new password "
        "(valid for one hour, works once): {link}\nIf you did not ask for a reset, do nothing."
    ),
}


def telegram_text(language: str | None, link: str) -> str:
    return TELEGRAM_TEXT.get(language or "ru", TELEGRAM_TEXT["ru"]).format(link=link)
