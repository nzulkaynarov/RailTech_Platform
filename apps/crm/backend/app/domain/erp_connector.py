"""Коннектор «ERP» (M3-CRM-02, ADR-0018): чистые правила адреса интеграционного API.

Админ вводит корень ERP (`https://erp.example.com`); путь интеграционного API
(`/api/integration/v1`, CONTRACTS §1) добавляет код. Если адрес вставили вместе с этим путём —
он отбрасывается, чтобы `/health` не стал `/api/integration/v1/api/integration/v1/health`.
"""

import ipaddress
from typing import Final
from urllib.parse import urlsplit

INTEGRATION_PREFIX: Final = "/api/integration/v1"
HEALTH_PATH: Final = f"{INTEGRATION_PREFIX}/health"
# Сопряжение по одноразовому коду и ротация ключей (M3-CRM-10, CONTRACTS §2).
PAIRING_ACCEPT_PATH: Final = f"{INTEGRATION_PREFIX}/pairing/accept"
PAIRING_ROTATE_PATH: Final = f"{INTEGRATION_PREFIX}/pairing/rotate"
_SCHEMES: Final = frozenset({"http", "https"})


def normalize_base_url(raw: str) -> str:
    """Без пробелов, завершающих `/` и лишнего префикса интеграционного API; пусто — не задан."""
    url = raw.strip().rstrip("/")
    if url.lower().endswith(INTEGRATION_PREFIX):
        url = url[: -len(INTEGRATION_PREFIX)].rstrip("/")
    return url


def base_url_problem(url: str) -> str | None:
    """Почему адрес не годится; None — адрес в порядке. Пустой адрес — тоже проблема."""
    try:
        parts = urlsplit(url)
        host = parts.hostname
    except ValueError as exc:
        return f"malformed url: {exc}"
    if parts.scheme.lower() not in _SCHEMES:
        return "scheme must be http or https"
    if not host:
        return "host is missing"
    if parts.query or parts.fragment:
        return "query and fragment are not allowed"
    if parts.username or parts.password:
        return "credentials in url are not allowed"
    return None


#: Внутренний адрес ERP в сети compose (сервис `erp-backend` есть в `ALLOWED_HOSTS` ERP).
DEFAULT_INTERNAL_ERP_URL: Final = "http://erp-backend:8000"


def is_internal_host(url: str) -> bool:
    """Внутренний адрес: имя сервиса Docker без точки (`erp-backend`) или IP частной сети."""
    host = urlsplit(url).hostname or ""
    try:
        return ipaddress.ip_address(host).is_private
    except ValueError:
        return bool(host) and "." not in host


def requires_https(url: str) -> bool:
    """В проде http допустим только внутри сети; внешний адрес — только https."""
    return urlsplit(url).scheme.lower() != "https" and not is_internal_host(url)


def health_url(base_url: str) -> str:
    return f"{normalize_base_url(base_url)}{HEALTH_PATH}"
