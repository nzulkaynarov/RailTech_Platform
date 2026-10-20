"""Адреса для кнопок бота: Telegram принимает в `url` только http(s) (FIX-34)."""

from urllib.parse import urlsplit


def is_http_url(value: object) -> bool:
    """`http(s)://host` без пробелов; другая схема (`javascript:`), пусто и мусор — нет."""
    if not isinstance(value, str) or not value or value != value.strip():
        return False
    if any(ch.isspace() for ch in value):
        return False
    try:
        parts = urlsplit(value)
    except ValueError:
        return False
    return parts.scheme in ("http", "https") and bool(parts.hostname)
