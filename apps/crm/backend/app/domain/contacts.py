"""Контакты клиента (Q-011): нормализация телефона и почты — чистые функции без I/O."""

import re
from typing import Final

from app.domain.bot_menu import normalize_phone
from app.domain.errors import Reason, ValidationFailedError

_EMAIL: Final = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
EMAIL_MAX: Final = 255


def contact_phone(raw: str | None) -> str | None:
    """Телефон из формы → E.164 тем же нормализатором, что и номер из Telegram; пусто → None."""
    if raw is None or not raw.strip():
        return None
    value = normalize_phone(raw)
    if value is None:
        raise ValidationFailedError(
            "phone must be in international format", reason=Reason.INVALID_PHONE, field="phone"
        )
    return value


def contact_email(raw: str | None) -> str | None:
    """Почта → нижний регистр без пробелов; пусто → None; без `@`/домена — ошибка поля."""
    if raw is None or not raw.strip():
        return None
    value = raw.strip().lower()
    if len(value) > EMAIL_MAX or not _EMAIL.fullmatch(value):
        raise ValidationFailedError("invalid email", reason=Reason.INVALID_EMAIL, field="email")
    return value


def suggested_name(first_name: str | None, username: str | None, phone: str) -> str:
    """Имя для контакта из Telegram: имя из профиля, иначе @username, иначе номер."""
    if first_name and first_name.strip():
        return first_name.strip()[:255]
    if username:
        return f"@{username}"
    return phone
