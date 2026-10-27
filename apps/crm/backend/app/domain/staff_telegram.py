"""Привязка Telegram сотрудником самим (W15-H6): одноразовый код старта. Чистые функции.

Сотрудник нажимает «Привязать Telegram» → ссылка `t.me/<бот>?start=staff_<код>`. Клиентский бот
один: код сотрудника отличается префиксом `staff_`, клиентские deep-link'и и обычный `/start` его не
используют и не затрагиваются. Код короткоживущий, одноразовый, в БД лежит хеш.
"""

import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta
from typing import Final

PREFIX: Final = "staff_"
CODE_TTL: Final = timedelta(minutes=10)
# 12 байт -> 16 символов алфавита Telegram deep-link (A-Za-z0-9_-); вместе с префиксом < 64.
_CODE_BYTES: Final = 12
_CODE_RE: Final = re.compile(r"^[A-Za-z0-9_-]{16}$")


def new_code() -> str:
    return secrets.token_urlsafe(_CODE_BYTES)


def hash_code(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


def same_code(code: str, stored_hash: str) -> bool:
    return hmac.compare_digest(hash_code(code), stored_hash)


def start_payload(code: str) -> str:
    return f"{PREFIX}{code}"


def staff_code_of(args: str | None) -> str | None:
    """Код сотрудника из аргумента `/start`; всё, что не `staff_<16 символов>` — не наше (None).

    Так клиентские deep-link'и (`/start ref_...`, `/start`) идут своим путём без изменений."""
    if not args or not args.startswith(PREFIX):
        return None
    code = args[len(PREFIX) :]
    return code if _CODE_RE.match(code) else None


def is_expired(expires_at: datetime, now: datetime) -> bool:
    return now >= expires_at


def deep_link(bot_username: str, code: str) -> str:
    return f"https://t.me/{bot_username.lstrip('@')}?start={start_payload(code)}"


def clean_username(username: str | None) -> str | None:
    value = (username or "").strip().lstrip("@")
    return value[:64] or None


LINKED: Final = {
    "ru": (
        "Telegram привязан к вашему профилю. Сюда будут приходить личные уведомления CRM. "
        "Если это сделали не вы, отвяжите Telegram в профиле Платформы."
    ),
    "uz": (
        "Telegram profilingizga ulandi. CRM shaxsiy bildirishnomalari shu yerga keladi. "
        "Agar buni siz qilmagan boʻlsangiz, Platforma profilida Telegramni uzing."
    ),
    "en": (
        "Telegram is linked to your profile. Personal CRM notifications will arrive here. "
        "If this was not you, unlink Telegram in your Platform profile."
    ),
}
INVALID: Final = {
    "ru": (
        "Ссылка привязки недействительна или устарела. "
        "Откройте профиль в Платформе и привяжите заново."
    ),
    "uz": "Ulash havolasi yaroqsiz yoki eskirgan. Platformada profilni ochib, qaytadan ulang.",
    "en": "This link is invalid or has expired. Open your profile in the Platform and link again.",
}
TAKEN: Final = {
    "ru": (
        "Этот Telegram уже привязан к другому сотруднику. "
        "Отвяжите его там или обратитесь к администратору."
    ),
    "uz": "Bu Telegram boshqa xodimga ulangan. U yerda uzing yoki administratorga murojaat qiling.",
    "en": (
        "This Telegram account is already linked to another employee. "
        "Unlink it there or ask an administrator."
    ),
}


def text(table: dict[str, str], language: str | None) -> str:
    return table.get(language or "ru", table["ru"])


# Telegram, привязанный сотрудником только что, не принимает ссылку сброса пароля: захваченная
# сессия не должна позволять привязать «свой» Telegram и сразу забрать учётную запись.
TRUST_AFTER: Final = timedelta(hours=24)


def telegram_trusted(linked_at: datetime | None, now: datetime) -> bool:
    """`None` — привязал администратор или привязка старая (самопривязка всегда ставит время)."""
    return linked_at is None or now - linked_at >= TRUST_AFTER
