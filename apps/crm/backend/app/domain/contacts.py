"""Контакты клиента (Q-011): нормализация телефона и почты — чистые функции без I/O."""

import re
from typing import Final

from app.domain.errors import Reason, ValidationFailedError
from app.domain.lead_sources import normalize_phone_e164

_EMAIL: Final = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
EMAIL_MAX: Final = 255


def contact_phone(raw: str | None) -> str | None:
    """Телефон из формы → E.164 единым нормализатором CRM (normalize_phone_e164); пусто → None."""
    if raw is None or not raw.strip():
        return None
    value = normalize_phone_e164(raw)
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


_DJANGO_USER: Final = re.compile(
    r"(^[-!#$%&'*+/=?^_`{}|~0-9A-Z]+(\.[-!#$%&'*+/=?^_`{}|~0-9A-Z]+)*\Z"
    r'|^"([\001-\010\013\014\016-\037!#-\[\]-\177]|\\[\001-\011\013\014\016-\177])*"\Z)',
    re.IGNORECASE,
)
_DJANGO_DOMAIN: Final = re.compile(
    r"((?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+)(?:[A-Z0-9-]{2,63}(?<!-))\Z", re.IGNORECASE
)


def partner_email(raw: str) -> str:
    """Почта кандидата в партнёры: правила ERP (`django.core.validators.validate_email`),
    чтобы CRM не принимала адрес, который ERP потом отвергнет; ошибка — у поля `email`."""
    value = raw.strip()
    if not value:
        return ""  # почта не обязательна: путь партнёра не останавливается на её отсутствии (ПК-1)
    user, at, domain = value.rpartition("@")
    ok = bool(at) and len(value) <= 254 and bool(_DJANGO_USER.match(user))
    if ok and not _DJANGO_DOMAIN.match(domain):
        try:
            ok = bool(_DJANGO_DOMAIN.match(domain.encode("idna").decode("ascii")))
        except UnicodeError:
            ok = False
    if not ok:
        raise ValidationFailedError("invalid email", reason=Reason.INVALID_EMAIL, field="email")
    return value.lower()


def suggested_name(first_name: str | None, username: str | None, phone: str) -> str:
    """Имя для контакта из Telegram: имя из профиля, иначе @username, иначе номер."""
    if first_name and first_name.strip():
        return first_name.strip()[:255]
    if username:
        return f"@{username}"
    return phone
