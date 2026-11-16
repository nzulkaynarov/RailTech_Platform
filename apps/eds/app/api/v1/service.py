"""Сервисные маршруты для других систем (не сотрудника) — ADR-0026.

`GET /api/v1/service/letters/{document_id}/pdf` — итоговый PDF отправленного исходящего письма для кабинета контрагента.
Зовёт только ERP по `Authorization: Bearer <SERVICE_TOKEN_ERP_TO_EDS>` (до двух токенов при ротации). Кому письмо и
видит ли его компания, решает ERP по своей проекции; EDS отдаёт только то, что уже ушло адресату: `letter_out` в статусе
`sent`, с номером ИСХ и итоговым PDF. Всё остальное — 404 без подробностей.
"""

import hmac
import uuid
from typing import Annotated, Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.api.deps import get_container, get_storage
from app.errors import not_found, unauthorized
from app.models import Document, DocumentRender
from app.services import renders
from app.services.storage import ObjectStorage

router = APIRouter(prefix="/api/v1/service", tags=["documents"])
_bearer = HTTPBearer(auto_error=False)


def erp_service(
    request: Request, credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]
) -> None:
    """Сервисный токен ERP; сравнение за постоянное время, пустой список токенов закрывает путь."""
    if credentials is None:
        raise unauthorized("missing")
    tokens = get_container(request).settings.erp_service_tokens
    presented = credentials.credentials.encode()
    if not any(hmac.compare_digest(presented, token.encode()) for token in tokens):
        raise unauthorized("invalid")


@router.get(
    "/letters/{document_id}/pdf",
    response_class=StreamingResponse,
    operation_id="downloadSentLetterPdfForErp",
    dependencies=[Depends(erp_service)],
)
async def download_sent_letter_pdf(
    document_id: uuid.UUID, request: Request, storage: Annotated[ObjectStorage, Depends(get_storage)]
) -> StreamingResponse:
    async with get_container(request).session_factory() as session:
        document = await session.get(Document, document_id)
        if document is None or document.kind != "letter_out" or document.status != "sent" or not document.number:
            raise not_found("Документ не найден.")
        render = await session.get(DocumentRender, document.pdf_hash) if document.pdf_hash else None
        if render is None or not render.final or render.status != "ready":
            raise not_found("Документ не найден.")
        number = document.number
    chunks = renders.stream(storage, render)
    first = await anext(chunks)
    name = quote(f"{number.replace('/', '-')}.pdf")

    async def body() -> Any:
        yield first
        async for chunk in chunks:
            yield chunk

    return StreamingResponse(
        body(),
        media_type="application/pdf",
        headers={"Content-Disposition": f"inline; filename*=UTF-8''{name}", "ETag": f'"{render.hash}"'},
    )
