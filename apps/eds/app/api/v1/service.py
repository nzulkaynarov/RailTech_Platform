"""Сервисные маршруты для других систем (не сотрудника) — ADR-0026.

`GET /api/v1/service/files/{file_id}?created_by=` — файл письма по заявке, пока он ещё ни к чему не привязан (РЕЗ-1).
`GET /api/v1/service/letters/{document_id}/pdf` — итоговый PDF отправленного исходящего письма для кабинета контрагента.
Зовёт только ERP по `Authorization: Bearer <SERVICE_TOKEN_ERP_TO_EDS>` (до двух токенов при ротации). Кому письмо и
видит ли его компания, решает ERP по своей проекции; EDS отдаёт только то, что уже ушло адресату: `letter_out` в статусе
`sent`, с номером ИСХ и итоговым PDF. Всё остальное — 404 без подробностей.
"""

import hmac
import uuid
from typing import Annotated, Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select

from app.api.deps import get_container, get_storage
from app.errors import not_found, unauthorized
from app.models import Document, DocumentRender, Employee, FileVersion, StoredFile
from app.services import files, renders
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


@router.get(
    "/files/{file_id}",
    response_class=StreamingResponse,
    operation_id="downloadRequestFileForErp",
    dependencies=[Depends(erp_service)],
)
async def download_request_file(
    file_id: uuid.UUID,
    created_by: Annotated[int, Query(ge=1)],
    request: Request,
    storage: Annotated[ObjectStorage, Depends(get_storage)],
) -> StreamingResponse:
    """Файл письма по заявке для ERP без резолюции (РЕЗ-1): непривязанный файл, загруженный `created_by`, либо файл
    входящего письма, которое `created_by` ведёт (видит файл по правилам EDS: чтение писем или участник поручений).
    Файл документа, поручения и чужого письма — 404."""
    async with get_container(request).session_factory() as session:
        stored = await session.get(StoredFile, file_id)
        if stored is None:
            raise not_found("Файл не найден.")
        if not (stored.letter_id or stored.document_id or stored.instruction_id):
            allowed = stored.created_by == created_by
        elif stored.letter_id and not (stored.document_id or stored.instruction_id):
            employee = (
                await session.execute(
                    select(Employee).where(Employee.crm_user_id == created_by, Employee.is_active.is_(True))
                )
            ).scalar_one_or_none()
            allowed = employee is not None and await files.can_view_file(session, employee, stored)
        else:
            allowed = False
        if not allowed:
            raise not_found("Файл не найден.")
        found = (
            await session.execute(
                select(FileVersion).where(FileVersion.file_id == file_id).order_by(FileVersion.version.desc()).limit(1)
            )
        ).scalar_one_or_none()
        if found is None:
            raise not_found("Файл не найден.")
        name, content_type, size, key = found.name, found.content_type, found.size, found.s3_key
    headers = {
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}",
        "Content-Length": str(size),
        "X-Content-Type-Options": "nosniff",
    }
    return StreamingResponse(storage.stream(key), media_type=content_type, headers=headers)
