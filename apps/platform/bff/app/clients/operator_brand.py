"""Логотип оператора до входа (ДВ-3).

Публичный `GET /operator` портала ERP → файл логотипа своей компании.

Оба адреса ERP публичные (без сессии и служебных токенов); BFF берёт только путь логотипа компании
(`/media/companies/<id>/logo/<файл>`), растр или SVG до 5 МБ, и отдаёт его с защитными заголовками.
"""

import re

import httpx

from app.clients.erp_company import LOGO_IMAGE_TYPES, MAX_LOGO_FILE_BYTES

_LOGO_PATH = re.compile(r"^/media/companies/\d+/logo/[^/?#]+$")
_TIMEOUT = httpx.Timeout(5.0)


async def fetch_operator_logo(erp_url: str) -> httpx.Response | None:
    base = erp_url.rstrip("/")
    async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=False) as client:
        try:
            operator = await client.get(f"{base}/api/portal/v1/operator")
            path = operator.json().get("logo_url") if operator.status_code == 200 else None
            if not isinstance(path, str) or not _LOGO_PATH.match(path):
                return None
            file = await client.get(f"{base}{path}")
        except (httpx.HTTPError, ValueError, AttributeError):
            return None
    mime = file.headers.get("content-type", "").split(";")[0].strip().lower()
    if (
        file.status_code != 200
        or len(file.content) > MAX_LOGO_FILE_BYTES
        or mime not in LOGO_IMAGE_TYPES
    ):
        return None
    return file
