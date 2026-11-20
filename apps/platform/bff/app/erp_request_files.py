"""Скачивание файла заявки клиента из ERP (СЦ-10) — общее для карточки письма и расчёта.

Права на файл решает ERP (сделка видна сотруднику, файл — исходник её заявки); BFF только
отдаёт поток как вложение, тип содержимого браузеру не доверяется.
"""

from __future__ import annotations

import re

from fastapi.responses import StreamingResponse

from app.api.eds_documents import FileStream
from app.clients.erp_company import erp_error
from app.deps import Authed

_ATTACHMENT = re.compile(r"^attachment(;|$)", re.IGNORECASE)


async def stream_request_file(authed: Authed, deal_id: int, file_id: int) -> StreamingResponse:
    upstream = await authed.call(
        "erp", "GET", f"/api/v1/crm/deals/{deal_id}/request-files/{file_id}/", stream=True
    )
    if upstream.status_code != 200:
        try:
            await upstream.aread()
            raise erp_error(upstream)
        finally:
            await upstream.aclose()
    disposition = upstream.headers.get("content-disposition", "")
    headers = {
        # Только вложение: имя и тип не дают браузеру открыть файл как страницу.
        "Content-Disposition": disposition if _ATTACHMENT.match(disposition) else "attachment",
        "Content-Security-Policy": "default-src 'none'; sandbox",
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "private, no-store",
    }
    return FileStream(upstream, headers, "application/octet-stream")
