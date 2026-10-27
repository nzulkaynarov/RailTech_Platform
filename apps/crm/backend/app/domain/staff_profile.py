"""Профиль сотрудника (W15-H6): телефон, часовой пояс, подпись, фото и замещение. Чистые функции.

Поля принадлежат CRM (ADR-0015); сотрудник правит только свои, должность задаёт админ. Правила
значений живут здесь, чтобы их проверяли тесты без БД; запись и S3 — `services/staff_profile.py`.
"""

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from functools import lru_cache
from typing import Final
from zoneinfo import ZoneInfo, available_timezones

DEFAULT_TIMEZONE: Final = "Asia/Tashkent"
PHONE_MIN_DIGITS: Final = 7
PHONE_MAX_DIGITS: Final = 15
SIGNATURE_MAX_LEN: Final = 1000
AVATAR_MAX_BYTES: Final = 1024 * 1024
AVATAR_PREFIX: Final = "staff-avatars"
DEPUTY_MAX_DAYS: Final = 366

_PHONE_CHARS: Final = re.compile(r"^\+?[\d\s().-]+$")
# Подпись магических байтов -> (тип, расширение). SVG не принимается: он исполняет скрипты.
_WEBP_RIFF: Final = b"RIFF"
_WEBP_TAG: Final = b"WEBP"
AVATAR_TYPES: Final = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}


class ProfileValueError(ValueError):
    """Значение поля профиля не прошло проверку; `reason` — код для `details.reason`."""

    def __init__(self, reason: str, field: str) -> None:
        super().__init__(f"{field}: {reason}")
        self.reason = reason
        self.field = field


def normalize_phone(raw: str) -> str | None:
    """`+` и цифры без пробелов и скобок; пусто — телефон очищен (None)."""
    text = raw.strip()
    if not text:
        return None
    if not _PHONE_CHARS.match(text):
        raise ProfileValueError("phone_invalid", "phone")
    digits = re.sub(r"\D", "", text)
    if not PHONE_MIN_DIGITS <= len(digits) <= PHONE_MAX_DIGITS:
        raise ProfileValueError("phone_invalid", "phone")
    return ("+" if text.startswith("+") else "") + digits


@lru_cache(maxsize=1)
def _known_zones() -> frozenset[str]:
    """`available_timezones()` читает диск: список строится один раз на процесс."""
    return frozenset(available_timezones())


def checked_timezone(name: str) -> str:
    """Имя пояса IANA из базы zoneinfo (регистр важен: `Asia/Tashkent`)."""
    value = name.strip()
    if value not in _known_zones():
        raise ProfileValueError("timezone_unknown", "timezone")
    return value


def checked_signature(text: str) -> str | None:
    """Подпись для писем: без нулевых байтов, ≤ 1000 символов; пусто — очищена."""
    value = text.replace("\r\n", "\n").strip()
    if "\x00" in value or len(value) > SIGNATURE_MAX_LEN:
        raise ProfileValueError("signature_invalid", "email_signature")
    return value or None


def sniff_image(data: bytes) -> str | None:
    """Тип картинки по первым байтам: PNG, JPEG или WebP; иное — None."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data[:4] == _WEBP_RIFF and data[8:12] == _WEBP_TAG:
        return "image/webp"
    return None


def checked_avatar(data: bytes, claimed_type: str | None) -> str:
    """Фото: не пусто, ≤ 1 МБ, настоящий PNG/JPEG/WebP (тип по содержимому, не по заголовку)."""
    if not data:
        raise ProfileValueError("avatar_empty", "avatar")
    if len(data) > AVATAR_MAX_BYTES:
        raise ProfileValueError("avatar_too_large", "avatar")
    detected = sniff_image(data)
    if detected is None:
        raise ProfileValueError("avatar_unsupported_type", "avatar")
    if claimed_type and claimed_type.split(";")[0].strip().lower() != detected:
        raise ProfileValueError("avatar_type_mismatch", "avatar")
    return detected


def avatar_key(user_id: int, token: str, content_type: str) -> str:
    """Ключ в бакете файлов CRM: `staff-avatars/<id>/<случайный>.<расширение>`."""
    return f"{AVATAR_PREFIX}/{user_id}/{token}.{AVATAR_TYPES[content_type]}"


@dataclass(frozen=True, slots=True)
class DeputyPeriod:
    """Кто видит очередь сотрудника на время отсутствия (включая обе даты)."""

    deputy_user_id: int
    date_from: date
    date_to: date

    def active_on(self, day: date) -> bool:
        return self.date_from <= day <= self.date_to


def checked_deputy(
    user_id: int, deputy_user_id: int, date_from: date, date_to: date, today: date
) -> DeputyPeriod:
    """Замещение: не себя, период не пустой и не в прошлом, не длиннее года."""
    if deputy_user_id == user_id:
        raise ProfileValueError("deputy_is_self", "deputy_user_id")
    if date_to < date_from:
        raise ProfileValueError("deputy_period_reversed", "date_to")
    if date_to < today:
        raise ProfileValueError("deputy_period_past", "date_to")
    if date_to - date_from > timedelta(days=DEPUTY_MAX_DAYS):
        raise ProfileValueError("deputy_period_too_long", "date_to")
    return DeputyPeriod(deputy_user_id, date_from, date_to)


def local_today(timezone: str, now: datetime) -> date:
    """Сегодняшняя дата в поясе сотрудника: замещение начинается и кончается по его календарю."""
    try:
        zone = ZoneInfo(timezone)
    except (KeyError, ValueError):
        zone = ZoneInfo(DEFAULT_TIMEZONE)
    return now.astimezone(zone).date()
