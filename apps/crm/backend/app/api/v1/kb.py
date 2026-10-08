"""База знаний для админа (PLAN Фаза 5): документы, чанки, тестовый поиск, пробелы, продукты."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, Path, Query, UploadFile, status
from sqlalchemy import select

from app.api.deps import ContainerDep, require
from app.domain.errors import NotFoundError
from app.models.kb import KbDocument, KbGap, Product
from app.schemas.kb_admin import (
    Created,
    KbChunkOut,
    KbDocumentOut,
    KbDocumentPatch,
    KbGapOut,
    KbGapPage,
    Language,
    ManualDocument,
    ProductIn,
    ProductOut,
    ResolveGap,
    SearchHitOut,
    SearchRequest,
    SearchResponse,
)
from app.schemas.leads import ActionResult
from app.security.principal import Principal
from app.services.kb import admin
from app.services.kb.admin import MAX_UPLOAD_BYTES, DocumentPatch
from app.services.kb.ingest import NewKbFile

router = APIRouter(prefix="/api/v1/kb", tags=["kb"])

GapStatus = Literal["open", "resolved", "ignored"]

Reader = Annotated[Principal, Depends(require("kb", "read"))]
Writer = Annotated[Principal, Depends(require("kb", "write"))]


def document_out(d: KbDocument) -> KbDocumentOut:
    return KbDocumentOut.model_validate(d, from_attributes=True)


@router.get("/documents", response_model=list[KbDocumentOut])
async def list_kb_documents(
    _: Reader, container: ContainerDep, active: bool | None = None
) -> list[KbDocumentOut]:
    async with container.session_factory() as session:
        return [document_out(d) for d in await admin.list_documents(session, active)]


@router.get("/documents/{document_id}", response_model=KbDocumentOut)
async def get_kb_document(document_id: int, _: Reader, container: ContainerDep) -> KbDocumentOut:
    async with container.session_factory() as session:
        document = await session.get(KbDocument, document_id)
    if document is None:
        raise NotFoundError("kb document not found")
    return document_out(document)


@router.post("/documents", response_model=Created, status_code=status.HTTP_201_CREATED)
async def upload_kb_document(
    who: Writer,
    container: ContainerDep,
    file: Annotated[UploadFile, File()],
    title: Annotated[str, Form(min_length=1, max_length=500)],
    language: Annotated[Language, Form()],
    product_key: Annotated[str | None, Form()] = None,
    gap_id: Annotated[int | None, Form()] = None,
) -> Created:
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    new = NewKbFile(
        title=title,
        filename=file.filename or "file",
        content=content,
        language=language,
        product_key=product_key or None,
        uploaded_by=who.user_id,
        mime=file.content_type,
    )
    return Created(id=await container.kb_admin.upload(who.actor, new, gap_id))


@router.post("/documents/manual", response_model=Created, status_code=status.HTTP_201_CREATED)
async def create_manual_document(
    body: ManualDocument, who: Writer, container: ContainerDep
) -> Created:
    document_id = await container.kb_admin.create_manual(
        who.actor, body.title, body.markdown, body.language, body.product_key, body.gap_id
    )
    return Created(id=document_id)


@router.patch("/documents/{document_id}", response_model=ActionResult)
async def update_kb_document(
    document_id: int, body: KbDocumentPatch, who: Writer, container: ContainerDep
) -> ActionResult:
    patch = DocumentPatch(body.title, body.is_active, body.product_key, body.clear_product)
    await container.kb_admin.update(who.actor, document_id, patch)
    return ActionResult()


@router.post("/documents/{document_id}/reingest", response_model=ActionResult)
async def reingest_kb_document(
    document_id: int, who: Writer, container: ContainerDep
) -> ActionResult:
    await container.kb_admin.reingest(who.actor, document_id)
    return ActionResult()


@router.get("/documents/{document_id}/chunks", response_model=list[KbChunkOut])
async def list_kb_chunks(document_id: int, _: Reader, container: ContainerDep) -> list[KbChunkOut]:
    async with container.session_factory() as session:
        rows = await admin.list_chunks(session, document_id)
    return [KbChunkOut.model_validate(c, from_attributes=True) for c in rows]


@router.post("/search", response_model=SearchResponse)
async def kb_test_search(body: SearchRequest, _: Reader, container: ContainerDep) -> SearchResponse:
    """«Что найдёт бот на этот вопрос»: тот же поиск и порог, что у диалогового агента."""
    cfg = await container.settings_service.get()
    result = await container.kb_search.search(
        body.query, product_key=body.product_key, top_k=body.top_k, language=body.language
    )
    hits = [SearchHitOut.model_validate(h, from_attributes=True) for h in result.hits]
    return SearchResponse(
        hits=hits,
        best_score=result.best_score,
        min_score=cfg.kb.min_score,
        confident=result.is_confident(cfg.kb.min_score),
        language=result.language,
    )


@router.get("/gaps", response_model=KbGapPage)
async def list_kb_gaps(
    _: Reader,
    container: ContainerDep,
    gap_status: Annotated[GapStatus, Query(alias="status")] = "open",
    language: Language | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> KbGapPage:
    async with container.session_factory() as session:
        rows, total = await admin.list_gaps(session, gap_status, language, limit, offset)
    return KbGapPage(items=[_gap_out(g) for g in rows], total=total)


def _gap_out(gap: KbGap) -> KbGapOut:
    return KbGapOut.model_validate(gap, from_attributes=True)


@router.post("/gaps/{gap_id}/ignore", response_model=ActionResult)
async def ignore_gap(gap_id: int, who: Writer, container: ContainerDep) -> ActionResult:
    await container.kb_admin.ignore_gap(who.actor, gap_id)
    return ActionResult()


@router.post("/gaps/{gap_id}/resolve", response_model=ActionResult)
async def resolve_gap(
    gap_id: int, body: ResolveGap, who: Writer, container: ContainerDep
) -> ActionResult:
    await container.kb_admin.resolve_gap(who.actor, gap_id, body.document_id)
    return ActionResult()


@router.post("/gaps/{gap_id}/reopen", response_model=ActionResult)
async def reopen_gap(gap_id: int, who: Writer, container: ContainerDep) -> ActionResult:
    await container.kb_admin.reopen_gap(who.actor, gap_id)
    return ActionResult()


@router.get("/products", response_model=list[ProductOut])
async def list_products(_: Reader, container: ContainerDep) -> list[ProductOut]:
    async with container.session_factory() as session:
        rows = (await session.scalars(select(Product).order_by(Product.key))).all()
    return [ProductOut.model_validate(p, from_attributes=True) for p in rows]


@router.put("/products/{key}", response_model=ActionResult)
async def upsert_product(
    key: Annotated[str, Path(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")],
    body: ProductIn,
    who: Writer,
    container: ContainerDep,
) -> ActionResult:
    await container.kb_admin.upsert_product(
        who.actor, key, body.name, body.description, body.is_active
    )
    return ActionResult()
