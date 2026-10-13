"""Коннектор «ERP» (M3-CRM-02, ADR-0018): чистые правила адреса интеграционного API.

Админ вводит корень ERP (`https://erp.example.com`); путь интеграционного API
(`/api/integration/v1`, CONTRACTS §1) добавляет код. Если адрес вставили вместе с этим путём —
он отбрасывается, чтобы `/health` не стал `/api/integration/v1/api/integration/v1/health`.
"""

from typing import Final
from urllib.parse import urlsplit

INTEGRATION_PREFIX: Final = "/api/integration/v1"
HEALTH_PATH: Final = f"{INTEGRATION_PREFIX}/health"
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


def health_url(base_url: str) -> str:
    return f"{normalize_base_url(base_url)}{HEALTH_PATH}"
