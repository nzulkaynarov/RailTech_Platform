"""Документы: `/api/v1/documents…` (eds.yaml, тег `documents`); правила — `services/documents.py`."""

import uuid
from typing import Annotated, Any
from urllib.parse import quote

from fastapi import APIRouter, Body, Depends, Header, Query
from fastapi.responses import StreamingResponse
from rt_bus.sqlalchemy import AsyncBus
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_bus, get_container, get_session, get_storage, require_permission
from app.container import Container
from app.errors import not_found
from app.models import DocumentRender, Employee
from app.schemas.documents import (
    Document,
    DocumentCreate,
    DocumentKind,
    DocumentPage,
    DocumentPaymentIn,
    DocumentPdf,
    DocumentStatus,
    DocumentSubmitIn,
    DocumentUpdate,
    LetterheadOut,
)
from app.schemas.pagination import Cursor, Limit
from app.security.permissions import EdsPermission as P
from app.services import documents, documents_read, idempotency, letterhead, payments, renders
from app.services.storage import ObjectStorage

router = APIRouter(prefix="/api/v1", tags=["documents"])

IdemKey = Annotated[str | None, Header(alias="Idempotency-Key", min_length=8, max_length=128)]
# Операции над документом: любое из прав (eds.yaml, x-rt-permissions); право на тип документа — внутри операции.
Reader = Annotated[
    Employee, Depends(require_permission(P.MEMOS_CREATE, P.MEMOS_APPROVE, P.APPROVALS_DECIDE, P.REGISTRY_READ))
]
Author = Annotated[Employee, Depends(require_permission(P.MEMOS_CREATE, P.LETTERS_REGISTER))]
Accountant = Annotated[Employee, Depends(require_permission(P.PAYMENTS_CONFIRM))]
Registrar = Annotated[Employee, Depends(require_permission(P.LETTERS_REGISTER))]
AnyEmployee = Annotated[Employee, Depends(require_permission())]
Session = Annotated[AsyncSession, Depends(get_session)]
Bus = Annotated[AsyncBus, Depends(get_bus)]
Storage = Annotated[ObjectStorage, Depends(get_storage)]
Box = Annotated[Container, Depends(get_container)]


@router.get("/documents", response_model=DocumentPage, operation_id="listDocuments")
async def list_documents(
    employee: Reader,
    session: Session,
    kind: Annotated[list[DocumentKind] | None, Query()] = None,
    status: Annotated[list[DocumentStatus] | None, Query()] = None,
    mine: bool = False,
    cursor: Cursor = None,
    limit: Limit = 50,
) -> DocumentPage:
    return await documents_read.list_page(
        session, employee, kinds=kind, statuses=status, mine=mine, cursor=cursor, limit=limit
    )


@router.post("/documents", response_model=Document, status_code=201, operation_id="createDocument")
async def create_document(
    body: DocumentCreate, employee: Author, session: Session, bus: Bus, idempotency_key: IdemKey = None
) -> Any:
    async with session.begin():

        async def create() -> Document:
            document = await documents.create(session, bus, employee=employee, data=body)
            return await documents_read.present(session, document)

        return await idempotency.run(
            session,
            crm_user_id=employee.crm_user_id,
            scope="POST /documents",
            key=idempotency_key,
            request_hash=idempotency.body_hash(body),
            status_code=201,
            action=create,
        )


@router.get("/documents/{document_id}", response_model=Document, operation_id="getDocument")
async def get_document(document_id: uuid.UUID, employee: Reader, session: Session) -> Document:
    return await documents_read.present(session, await documents_read.get_visible(session, employee, document_id))


@router.patch("/documents/{document_id}", response_model=Document, operation_id="updateDocument")
async def update_document(document_id: uuid.UUID, body: DocumentUpdate, employee: Author, session: Session) -> Document:
    async with session.begin():
        document = await documents.update(session, employee=employee, document_id=document_id, edits=body)
        return await documents_read.present(session, document)


@router.post("/documents/{document_id}/submit", response_model=Document, operation_id="submitDocument")
async def submit_document(
    document_id: uuid.UUID,
    employee: Author,
    session: Session,
    bus: Bus,
    storage: Storage,
    box: Box,
    body: Annotated[DocumentSubmitIn | None, Body()] = None,
) -> Document:
    async with session.begin():
        document = await documents.submit(
            session, bus, employee=employee, document_id=document_id, edits=body, storage=storage
        )
        result = await documents_read.present(session, document)
    await box.defer_render(renders.take_pending(session))
    return result


# --- письмо на бланке (P4) ------------------------------------------------------------------------------------------


async def _render_of(session: AsyncSession, employee: Employee, document_id: uuid.UUID) -> DocumentRender:
    document = await documents_read.get_visible(session, employee, document_id)
    render = await session.get(DocumentRender, document.pdf_hash) if document.pdf_hash else None
    # PDF без знака «ПРОЕКТ», построенный до SIGN-1, не выдаётся: для экрана «не запрашивался» — он запросит заново.
    if render is None or renders.is_unmarked_draft(render):
        raise not_found("PDF письма не запрашивался.")
    if not render.final and not documents.may_open_pdf(employee, document):
        raise not_found("Документ не найден.")  # проект — только автору и делопроизводителю переданного (SIGN-1)
    return render


@router.post(
    "/documents/{document_id}/pdf", response_model=DocumentPdf, status_code=202, operation_id="requestDocumentPdf"
)
async def request_document_pdf(document_id: uuid.UUID, employee: Author, session: Session, box: Box) -> DocumentPdf:
    async with session.begin():
        document = await documents.get_for_pdf(session, employee=employee, document_id=document_id)
        result = renders.present(await renders.request(session, document))
    await box.defer_render(renders.take_pending(session))
    return result


@router.get("/documents/{document_id}/pdf", response_model=DocumentPdf, operation_id="getDocumentPdf")
async def get_document_pdf(document_id: uuid.UUID, employee: Reader, session: Session) -> DocumentPdf:
    return renders.present(await _render_of(session, employee, document_id))


@router.get(
    "/documents/{document_id}/pdf/file",
    response_class=StreamingResponse,
    operation_id="downloadDocumentPdf",
)
async def download_document_pdf(
    document_id: uuid.UUID, employee: Reader, session: Session, storage: Storage
) -> StreamingResponse:
    render = await _render_of(session, employee, document_id)
    document = await documents_read.get_visible(session, employee, document_id)
    chunks = renders.stream(storage, render)
    first = await anext(chunks)  # не готов — 409 до заголовков ответа
    name = quote(f"{(document.number or 'letter').replace('/', '-')}.pdf")

    async def body() -> Any:
        yield first
        async for chunk in chunks:
            yield chunk

    return StreamingResponse(
        body(),
        media_type="application/pdf",
        headers={"Content-Disposition": f"inline; filename*=UTF-8''{name}", "ETag": f'"{render.hash}"'},
    )


@router.post(
    "/documents/{document_id}/registration-request",
    response_model=Document,
    operation_id="requestDocumentRegistration",
)
async def request_document_registration(document_id: uuid.UUID, employee: Author, session: Session) -> Document:
    async with session.begin():
        document = await documents.request_registration(session, employee=employee, document_id=document_id)
        return await documents_read.present(session, document)


@router.post("/documents/{document_id}/send", response_model=Document, operation_id="sendDocument")
async def send_document(
    document_id: uuid.UUID, employee: Registrar, session: Session, bus: Bus, storage: Storage, box: Box
) -> Document:
    async with session.begin():
        document = await documents.send_again(session, bus, storage, employee=employee, document_id=document_id)
        result = await documents_read.present(session, document)
    await box.defer_render(renders.take_pending(session))
    return result


@router.get("/letterhead", response_model=LetterheadOut, operation_id="getLetterhead")
async def get_letterhead(employee: AnyEmployee, session: Session) -> LetterheadOut:
    row = await letterhead.current(session)
    if row is None:
        return LetterheadOut(
            configured=False,
            company_name=None,
            requisites=[],
            signatory_name=None,
            signatory_position=None,
            has_logo=False,
            updated_at=None,
        )
    return LetterheadOut(
        configured=True,
        company_name=row.company_name or None,
        requisites=letterhead.requisites(row),
        signatory_name=row.signatory_name or None,
        signatory_position=row.signatory_position or None,
        has_logo=row.logo_sha256 is not None,
        updated_at=row.updated_at,
    )


@router.post("/documents/{document_id}/payment", response_model=Document, operation_id="payDocument")
async def pay_document(
    document_id: uuid.UUID, body: DocumentPaymentIn, employee: Accountant, session: Session, bus: Bus
) -> Document:
    async with session.begin():
        document = await payments.pay(session, bus, employee=employee, document_id=document_id, body=body)
        return await documents_read.present(session, document)
