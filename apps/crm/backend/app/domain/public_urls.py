"""Публичные адреса систем из окружения (W15-H8a): Платформа и CRM для ссылок в письмах.

Явный адрес (`*_PUBLIC_URL`) главнее домена (`*_DOMAIN`); пусто и там, и там — адреса нет (None),
а не `localhost`: письмо со ссылкой в никуда хуже честной ошибки.
"""

from typing import Final
from urllib.parse import urlsplit

# Значение по умолчанию `company.crm_base_url` в схеме настроек: «админ ничего не задавал».
CRM_BASE_URL_SCHEMA_DEFAULT: Final = "http://localhost"
_SCHEMES: Final = ("http://", "https://")


def public_url(url: str, domain: str) -> str | None:
    """Базовый адрес без хвостового `/`: явный `url`, иначе `https://<domain>`; нет обоих — None."""
    explicit = url.strip().rstrip("/")
    if explicit:
        return explicit
    host = domain.strip().rstrip("/")
    if not host:
        return None
    return host if host.startswith(_SCHEMES) else f"https://{host}"


def is_schema_default(crm_base_url: str) -> bool:
    """Значение `company.crm_base_url` — заводское (`http://localhost`), а не выбор админа."""
    return crm_base_url.strip().rstrip("/") in ("", CRM_BASE_URL_SCHEMA_DEFAULT)


def is_local_url(url: str) -> bool:
    """Адрес ведёт на этот же компьютер (localhost, 127.x, `*.localhost`)."""
    host = (urlsplit(url.strip()).hostname or "").lower()
    return (
        host in {"localhost", "0.0.0.0", "::1"}  # noqa: S104
        or host.endswith(".localhost")
        or host.startswith("127.")
    )
