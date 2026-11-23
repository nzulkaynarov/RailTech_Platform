"""Шаблоны писем и служебок (`/api/v1/templates…`, eds.yaml, тег `documents`; TPL-4, план 3.6); правила —
`services/letter_templates.py`. Читают все, кто создаёт документы; правят делопроизводитель и администратор."""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Query, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_container, get_session, get_storage, require_permission
from app.container import Container
from app.errors import not_found
from app.models import DocumentRender, Employee
from app.schemas.letter_templates import (
    LetterTemplateIn,
    LetterTemplateList,
    LetterTemplateOut,
    TemplateKind,
    TemplatePreview,
    TemplatePreviewIn,
)
from app.security.permissions import EdsPermission as P
from app.services import letter_body, letter_templates, renders
from app.services.storage import ObjectStorage

router = APIRouter(prefix="/api/v1/templates", tags=["documents"])
# Предпросмотр — отдельный ресурс: `templates/preview/{hash}` спорил бы с `templates/{id}/reset`
previews = APIRouter(prefix="/api/v1/template-previews", tags=["documents"])

Reader = Annotated[Employee, Depends(require_permission(P.MEMOS_CREATE, P.LETTERS_REGISTER, P.BUS_MANAGE))]
Editor = Annotated[Employee, Depends(require_permission(P.LETTERS_REGISTER, P.BUS_MANAGE))]
Session = Annotated[AsyncSession, Depends(get_session)]
Storage = Annotated[ObjectStorage, Depends(get_storage)]
Box = Annotated[Container, Depends(get_container)]
RenderHash = Annotated[str, Path(pattern=r"^[0-9a-f]{64}$")]


@router.get("", response_model=LetterTemplateList, operation_id="listLetterTemplates")
async def list_templates(
    employee: Reader, session: Session, kind: Annotated[TemplateKind | None, Query()] = None
) -> LetterTemplateList:
    async with session.begin():
        return await letter_templates.list_all(session, kind)


@router.post(
    "", response_model=LetterTemplateOut, status_code=status.HTTP_201_CREATED, operation_id="createLetterTemplate"
)
async def create_template(body: LetterTemplateIn, employee: Editor, session: Session) -> LetterTemplateOut:
    async with session.begin():
        return await letter_templates.create(session, employee, body)


@router.get("/{template_id}", response_model=LetterTemplateOut, operation_id="getLetterTemplate")
async def get_template(template_id: uuid.UUID, employee: Reader, session: Session) -> LetterTemplateOut:
    async with session.begin():
        return await letter_templates.get(session, template_id)


@router.put("/{template_id}", response_model=LetterTemplateOut, operation_id="updateLetterTemplate")
async def update_template(
    template_id: uuid.UUID, body: LetterTemplateIn, employee: Editor, session: Session
) -> LetterTemplateOut:
    async with session.begin():
        return await letter_templates.update_one(session, employee, template_id, body)


@router.post("/{template_id}/reset", response_model=LetterTemplateOut, operation_id="resetLetterTemplate")
async def reset_template(template_id: uuid.UUID, employee: Editor, session: Session) -> LetterTemplateOut:
    async with session.begin():
        return await letter_templates.reset(session, employee, template_id)


@router.delete(
    "/{template_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    operation_id="deleteLetterTemplate",
)
async def delete_template(template_id: uuid.UUID, employee: Editor, session: Session) -> Response:
    async with session.begin():
        await letter_templates.delete(session, template_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _preview(row: DocumentRender) -> TemplatePreview:
    return TemplatePreview(
        hash=row.hash,
        status=row.status,
        error=row.error,
        pages=row.pages,
    )


async def _preview_row(session: AsyncSession, render_hash: str) -> DocumentRender:
    row = await session.get(DocumentRender, render_hash)
    if row is None or not row.payload.get("preview"):
        raise not_found("Предпросмотр не найден.")
    return row


@previews.post("", response_model=TemplatePreview, status_code=202, operation_id="previewLetterTemplate")
async def preview_template(body: TemplatePreviewIn, employee: Reader, session: Session, box: Box) -> TemplatePreview:
    """PDF варианта на бланке без сохранения: тот же рендер и кэш по хешу, что у писем; повтор — без новой работы."""
    async with session.begin():
        row = await renders.request_preview(session, letter_body.clean(body.body), body.kind)
        result = _preview(row)
    await box.defer_render(renders.take_pending(session))
    return result


@previews.get("/{preview_id}", response_model=TemplatePreview, operation_id="getLetterTemplatePreview")
async def get_preview(preview_id: RenderHash, employee: Reader, session: Session) -> TemplatePreview:
    return _preview(await _preview_row(session, preview_id))


@previews.get("/{preview_id}/file", response_class=StreamingResponse, operation_id="downloadLetterTemplatePreview")
async def download_preview(
    preview_id: RenderHash, employee: Reader, session: Session, storage: Storage
) -> StreamingResponse:
    row = await _preview_row(session, preview_id)
    chunks = renders.stream(storage, row)
    first = await anext(chunks)

    async def body() -> Any:
        yield first
        async for chunk in chunks:
            yield chunk

    return StreamingResponse(body(), media_type="application/pdf", headers={"ETag": f'"{row.hash}"'})
