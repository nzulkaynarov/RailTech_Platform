"""Адрес CRM для ссылок из Telegram (`company.crm_base_url`): чистая проверка для «Состояния»."""

from typing import Final
from urllib.parse import urlsplit

_LOCAL_HOSTS: Final = frozenset({"localhost", "127.0.0.1", "0.0.0.0", "::1"})  # noqa: S104


def crm_url_problem(url: str) -> str | None:
    """Почему ссылки на CRM из Telegram не откроются у сотрудника; None — адрес годится."""
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower()
    if not host:
        return "адрес CRM не задан — ссылки из Telegram не откроются"
    if host in _LOCAL_HOSTS or host.endswith(".localhost"):
        return (
            "адрес CRM указывает на localhost — ссылки из Telegram "
            "откроются только на этом компьютере"
        )
    if parts.scheme != "https":
        return "адрес CRM без https — Telegram не покажет кнопку «Открыть в CRM»"
    return None
