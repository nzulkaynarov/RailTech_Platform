"""Файл письма клиента из EDS для заявки без резолюции (РЕЗ-1): сервисный путь `GET /api/v1/service/files/{id}`.

Зовётся из задачи после коммита, не из транзакции заявки. `None` — EDS файла не отдаёт (404: чужой, уже привязанный к
другому объекту, нет такого) — повторять незачем; сбой сети или 5xx — исключение `EdsFileUnavailable`, задача повторит.
"""

from __future__ import annotations

from typing import Optional
from urllib.parse import unquote

import httpx
from django.conf import settings

TIMEOUT_SECONDS = 15


class EdsFileUnavailable(Exception):
    """Сеть или EDS временно недоступны."""


def fetch_request_file(file_id: str, created_by: int, letter_number: str = "") -> Optional[tuple[str, bytes]]:
    token = settings.SERVICE_TOKEN_ERP_TO_EDS
    if not token:
        raise EdsFileUnavailable("SERVICE_TOKEN_ERP_TO_EDS is not set")
    params: dict[str, object] = {"created_by": int(created_by)}
    if letter_number:
        params["letter_number"] = letter_number
    try:
        response = httpx.get(
            f"{settings.EDS_INTERNAL_URL}/api/v1/service/files/{file_id}",
            params=params,
            headers={"Authorization": f"Bearer {token}"},
            timeout=TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as exc:
        raise EdsFileUnavailable(str(exc)) from exc
    if response.status_code == 404:
        return None
    if response.status_code != 200:
        raise EdsFileUnavailable(f"HTTP {response.status_code}")
    disposition = response.headers.get("content-disposition", "")
    marker = "filename*=UTF-8''"
    name = unquote(disposition.split(marker, 1)[1]) if marker in disposition else "letter"
    return name[:255], response.content
