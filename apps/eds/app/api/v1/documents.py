"""Документы: `/api/v1/documents…` (eds.yaml, тег `documents`); правила — `services/documents.py`."""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, Header, Query
from rt_bus.sqlalchemy import AsyncBus
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_bus, get_session, require_permission
from app.models import Employee
from app.schemas.documents import (
    Document,
    DocumentCreate,
    DocumentKind,
    DocumentPage,
    DocumentStatus,
    DocumentSubmitIn,
)
from app.schemas.pagination import Cursor, Limit
from app.security.permissions import EdsPermission as P
from app.services import documents, documents_read, idempotency

router = APIRouter(prefix="/api/v1", tags=["documents"])

IdemKey = Annotated[str | None, Header(alias="Idempotency-Key", min_length=8, max_length=128)]
# Операции над документом: любое из прав (eds.yaml, x-rt-permissions); право на тип документа — внутри операции.
Reader = Annotated[
    Employee, Depends(require_permission(P.MEMOS_CREATE, P.MEMOS_APPROVE, P.APPROVALS_DECIDE, P.REGISTRY_READ))
]
Author = Annotated[Employee, Depends(require_permission(P.MEMOS_CREATE, P.LETTERS_REGISTER))]
Session = Annotated[AsyncSession, Depends(get_session)]
Bus = Annotated[AsyncBus, Depends(get_bus)]


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


@router.post("/documents/{document_id}/submit", response_model=Document, operation_id="submitDocument")
async def submit_document(
    document_id: uuid.UUID,
    employee: Author,
    session: Session,
    bus: Bus,
    body: Annotated[DocumentSubmitIn | None, Body()] = None,
) -> Document:
    async with session.begin():
        document = await documents.submit(session, bus, employee=employee, document_id=document_id, edits=body)
        return await documents_read.present(session, document)
