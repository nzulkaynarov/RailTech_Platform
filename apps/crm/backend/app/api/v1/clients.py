"""Клиенты, документы, привязка Telegram, сервисные запросы (PLAN Фаза 6, SPEC §10.1)."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import ContainerDep, require
from app.domain.errors import NotFoundError
from app.models.clients import Client, Document, DocumentAccessLog, ServiceRequest
from app.models.leads import Lead, TelegramIdentity
from app.repositories import clients as clients_repo
from app.repositories import service_requests
from app.repositories.service_requests import RequestStatus
from app.schemas.clients import (
    AccessOut,
    ClientCreate,
    ClientDetail,
    ClientListItem,
    ClientOut,
    ClientUpdate,
    DocType,
    DocumentOut,
    DocumentUpdate,
    IdentityOut,
    LeadBrief,
    LinkTelegram,
    MakeCustomer,
    ServiceRequestClose,
    ServiceRequestItem,
    ServiceRequestOut,
)
from app.schemas.kb_admin import Created
from app.schemas.leads import ActionResult
from app.security import audit
from app.security.principal import Principal
from app.services.documents import MAX_BYTES, NewDocument

router = APIRouter(prefix="/api/v1", tags=["clients"])

ClientReader = Annotated[Principal, Depends(require("clients", "read"))]
ClientWriter = Annotated[Principal, Depends(require("clients", "write"))]
DocReader = Annotated[Principal, Depends(require("documents", "read"))]
DocWriter = Annotated[Principal, Depends(require("documents", "write"))]


def _client_out(c: Client) -> ClientOut:
    return ClientOut.model_validate(c, from_attributes=True)


@router.get("/clients", response_model=list[ClientListItem])
async def list_clients(
    _: ClientReader, container: ContainerDep, q: Annotated[str | None, Query(max_length=100)] = None
) -> list[ClientListItem]:
    async with container.session_factory() as session:
        rows = await clients_repo.list_with_stats(session, q, 500)
    return [
        ClientListItem(**_client_out(c).model_dump(), open_deals=deals, last_activity_at=last)
        for c, deals, last in rows
    ]


@router.post("/clients", response_model=Created, status_code=status.HTTP_201_CREATED)
async def create_client(body: ClientCreate, who: ClientWriter, container: ContainerDep) -> Created:
    return Created(id=await container.client_service.create(who, body.name, body.inn, body.segment))


@router.get("/clients/{client_id}", response_model=ClientDetail)
async def get_client(client_id: int, _: ClientReader, container: ContainerDep) -> ClientDetail:
    async with container.session_factory() as session:
        client = await session.get(Client, client_id)
        if client is None:
            raise NotFoundError("client not found")
        leads = (await session.scalars(select(Lead).where(Lead.client_id == client_id))).all()
        linked = await _identities(session, TelegramIdentity.client_id == client_id)
        candidates = await _identities(
            session,
            TelegramIdentity.lead_id.in_([lead.id for lead in leads]),
            TelegramIdentity.client_id.is_(None),
        )
        requests = (
            await session.scalars(
                select(ServiceRequest)
                .where(ServiceRequest.client_id == client_id)
                .order_by(ServiceRequest.id.desc())
            )
        ).all()
    return ClientDetail(
        **_client_out(client).model_dump(),
        identities=linked,
        candidates=candidates,
        leads=[LeadBrief.model_validate(lead, from_attributes=True) for lead in leads],
        service_requests=[
            ServiceRequestOut.model_validate(r, from_attributes=True) for r in requests
        ],
    )


async def _identities(session: AsyncSession, *conditions: object) -> list[IdentityOut]:
    rows = (await session.scalars(select(TelegramIdentity).where(*conditions))).all()  # type: ignore[arg-type]
    return [IdentityOut.model_validate(i, from_attributes=True) for i in rows]


@router.patch("/clients/{client_id}", response_model=ActionResult)
async def update_client(
    client_id: int, body: ClientUpdate, who: ClientWriter, container: ContainerDep
) -> ActionResult:
    await container.client_service.update(who, client_id, body.model_dump(exclude_unset=True))
    return ActionResult()


@router.post("/clients/{client_id}/telegram", response_model=ActionResult)
async def link_telegram(
    client_id: int, body: LinkTelegram, who: ClientWriter, container: ContainerDep
) -> ActionResult:
    await container.client_service.link_identity(who, client_id, body.tg_user_id)
    return ActionResult()


@router.delete("/clients/{client_id}/telegram/{tg_user_id}", response_model=ActionResult)
async def unlink_telegram(
    client_id: int, tg_user_id: int, who: ClientWriter, container: ContainerDep
) -> ActionResult:
    await container.client_service.unlink_identity(who, client_id, tg_user_id)
    return ActionResult()


@router.post(
    "/leads/{lead_id}/actions/make_customer",
    response_model=Created,
    status_code=status.HTTP_201_CREATED,
)
async def make_customer(
    lead_id: int, body: MakeCustomer, who: ClientWriter, container: ContainerDep
) -> Created:
    """«Сделать клиентом» / «Передать в бэк-офис» (ADR-0022).

    Ошибки (ADR-0017, `details.reason`): `deal_not_closed` (409), `not_lead_owner` (403),
    `handoff_no_consent` (422 — в режиме `erp` лид не давал согласие, ERP его не выдумывает),
    `telegram_linked_elsewhere` (409), `erp_not_configured` (409), `erp_unavailable` (502).
    """
    client_id = await container.client_service.make_customer(
        who, lead_id, body.client_id, body.new_client_name
    )
    return Created(id=client_id)


@router.get("/service-requests", response_model=list[ServiceRequestItem])
async def list_service_requests(
    _: ClientReader,
    container: ContainerDep,
    status_: Annotated[RequestStatus, Query(alias="status")] = "open",
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> list[ServiceRequestItem]:
    """Запросы клиентов (Q-017): открытые — во «Входящих», кто ждёт дольше, первыми."""
    async with container.session_factory() as session:
        rows = await service_requests.list_with_clients(session, status_, limit)
    return [
        ServiceRequestItem(
            id=r.id,
            client_id=r.client_id,
            client_name=name,
            lead_id=r.lead_id,
            summary=r.summary,
            status=r.status,
            resolution=r.resolution,
            closed_at=r.closed_at,
            created_at=r.created_at,
        )
        for r, name in rows
    ]


@router.post("/service-requests/{request_id}/close", response_model=ActionResult)
async def close_service_request(
    request_id: int, body: ServiceRequestClose, who: ClientWriter, container: ContainerDep
) -> ActionResult:
    await container.client_service.close_service_request(who, request_id, body.resolution)
    return ActionResult()


@router.get("/documents", response_model=list[DocumentOut])
async def list_documents(
    _: DocReader,
    container: ContainerDep,
    client_id: int | None = None,
    type: DocType | None = None,
) -> list[DocumentOut]:
    stmt = select(Document).order_by(Document.doc_date.desc().nulls_last(), Document.id.desc())
    if client_id is not None:
        stmt = stmt.where(Document.client_id == client_id)
    if type is not None:
        stmt = stmt.where(Document.type == type)
    async with container.session_factory() as session:
        rows = (await session.scalars(stmt.limit(500))).all()
    return [DocumentOut.model_validate(d, from_attributes=True) for d in rows]


@router.post("/documents", response_model=Created, status_code=status.HTTP_201_CREATED)
async def upload_document(
    who: DocWriter,
    container: ContainerDep,
    file: Annotated[UploadFile, File()],
    client_id: Annotated[int, Form()],
    type: Annotated[DocType, Form()],
    title: Annotated[str, Form(min_length=1, max_length=500)],
    number: Annotated[str | None, Form(max_length=64)] = None,
    doc_date: Annotated[date | None, Form()] = None,
    visible: Annotated[bool, Form()] = True,
) -> Created:
    content = await file.read(MAX_BYTES + 1)
    new = NewDocument(
        client_id=client_id,
        type=type,
        title=title,
        filename=file.filename or "document",
        content=content,
        number=number,
        doc_date=doc_date,
        visible=visible,
        mime=file.content_type,
    )
    return Created(id=await container.document_service.upload(who, new))


@router.patch("/documents/{document_id}", response_model=ActionResult)
async def update_document(
    document_id: int, body: DocumentUpdate, who: DocWriter, container: ContainerDep
) -> ActionResult:
    async with container.session_factory() as session, session.begin():
        row = await session.get(Document, document_id, with_for_update=True)
        if row is None:
            raise NotFoundError("document not found")
        changes = body.model_dump(exclude_unset=True)
        before = {k: str(getattr(row, k)) for k in changes}
        for key, value in changes.items():
            setattr(row, key, value)
        await audit.record(
            session,
            who.actor,
            "document.update",
            "document",
            document_id,
            before=before,
            after={k: str(v) for k, v in changes.items()},
        )
    return ActionResult()


@router.get("/documents/{document_id}/download")
async def download_document(document_id: int, who: DocReader, container: ContainerDep) -> Response:
    content, filename, mime = await container.document_service.download(who, document_id)
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return Response(content, media_type=mime, headers=headers)


@router.get("/documents/{document_id}/access", response_model=list[AccessOut])
async def document_access(
    document_id: int, _: DocReader, container: ContainerDep
) -> list[AccessOut]:
    async with container.session_factory() as session:
        rows = (
            await session.scalars(
                select(DocumentAccessLog)
                .where(DocumentAccessLog.document_id == document_id)
                .order_by(DocumentAccessLog.id.desc())
                .limit(200)
            )
        ).all()
    return [AccessOut.model_validate(r, from_attributes=True) for r in rows]
