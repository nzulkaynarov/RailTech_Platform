"""CRM · База знаний: документы, поиск, пробелы, продукты и песочница бота (контракт: tag `kb`,
0.11.0).

BFF только проксирует к CRM с токеном сотрудника и проверяет раздел каталога. Чтение — раздел
`crm.leads` или `admin` (любой уровень: у обоих есть право CRM `kb:read`); правка, переиндексация,
пробелы и песочница — `admin: full` (`kb:write`, `sandbox:use`). Формат документа, размер файла
(25 МБ), закрытие пробела, песочницу и порог поиска решает CRM. Удаления документов в CRM нет:
«выключить» — `PATCH is_active`.

Загрузка файла: BFF multipart не разбирает — читает тело потоком до предела (`MAX_BODY_BYTES`: 25
МБ файла и запас на поля формы) и передаёт CRM как есть с тем же `Content-Type` (граница
multipart), так что лишнего разбора и зависимостей нет, а память ограничена размером файла.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Query, Request, Response, status

from app.clients import crm_models as crm
from app.clients.crm_proxy import CrmProxy
from app.deps import Authed, require, require_any
from app.errors import PlatformError
from app.schemas_integrations import ActionOk
from app.schemas_kb import (
    CreatedId,
    KbChunk,
    KbChunkList,
    KbDocument,
    KbDocumentList,
    KbDocumentPatch,
    KbGap,
    KbGapPage,
    KbGapResolveIn,
    KbManualDocumentIn,
    KbProduct,
    KbProductList,
    KbSearchIn,
    KbSearchResult,
    Language,
    SandboxMessageIn,
    SandboxTurn,
)

router = APIRouter(tags=["kb"])

API = "/api/v1"
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
# Файл до 25 МБ плюс поля формы и границы multipart.
MAX_BODY_BYTES = MAX_UPLOAD_BYTES + 64 * 1024

Reader = Annotated[Authed, Depends(require_any(("crm.leads", "read"), ("admin", "read")))]
Admin = Annotated[Authed, Depends(require("admin", "full"))]
DocumentId = Annotated[int, Path(ge=1)]
GapId = Annotated[int, Path(ge=1)]


def _crm(authed: Authed) -> CrmProxy:
    return CrmProxy(authed.call)


def _action(body: Any) -> ActionOk:
    return ActionOk.model_validate(body)


# --- документы ----------------------------------------------------------------------------------


@router.get("/crm/kb/documents", response_model=KbDocumentList, operation_id="listKbDocuments")
async def list_documents(authed: Reader, active: bool | None = None) -> KbDocumentList:
    rows = await _crm(authed).get_list(
        crm.KbDocumentOut,
        f"{API}/kb/documents",
        params=None if active is None else {"active": str(active).lower()},
    )
    return KbDocumentList(
        items=[KbDocument.model_validate(r.model_dump(mode="json")) for r in rows]
    )


def _too_large() -> PlatformError:
    return PlatformError(
        "VALIDATION_FAILED",
        "Файл больше 25 МБ.",
        status_code=422,
        details={"fields": ["file"], "reason": "file_too_large", "max_bytes": MAX_UPLOAD_BYTES},
    )


async def _read_limited(request: Request) -> bytes:
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        raise _too_large()
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_BODY_BYTES:
            raise _too_large()
    return bytes(body)


@router.post(
    "/crm/kb/documents",
    response_model=CreatedId,
    status_code=status.HTTP_201_CREATED,
    operation_id="uploadKbDocument",
)
async def upload_document(request: Request, authed: Admin) -> CreatedId:
    content_type = request.headers.get("content-type", "")
    if not content_type.lower().startswith("multipart/form-data"):
        raise PlatformError(
            "VALIDATION_FAILED",
            "Файл нужно передать формой multipart.",
            status_code=422,
            details={"fields": ["file"], "reason": "multipart_required"},
        )
    body = await _read_limited(request)
    out = await _crm(authed).get_model(
        crm.Created,
        "POST",
        f"{API}/kb/documents",
        expected=201,
        content=body,
        content_type=content_type,
        probe=True,
    )
    return CreatedId(id=out.id)


@router.post(
    "/crm/kb/documents/manual",
    response_model=CreatedId,
    status_code=status.HTTP_201_CREATED,
    operation_id="createManualKbDocument",
)
async def create_manual_document(body: KbManualDocumentIn, authed: Admin) -> CreatedId:
    out = await _crm(authed).get_model(
        crm.Created,
        "POST",
        f"{API}/kb/documents/manual",
        expected=201,
        json=body.model_dump(),
        probe=True,
    )
    return CreatedId(id=out.id)


@router.get("/crm/kb/documents/{id}", response_model=KbDocument, operation_id="getKbDocument")
async def get_document(id: DocumentId, authed: Reader) -> KbDocument:
    out = await _crm(authed).get_model(crm.KbDocumentOut, "GET", f"{API}/kb/documents/{id}")
    return KbDocument.model_validate(out.model_dump(mode="json"))


@router.patch("/crm/kb/documents/{id}", response_model=ActionOk, operation_id="updateKbDocument")
async def update_document(id: DocumentId, body: KbDocumentPatch, authed: Admin) -> ActionOk:
    return _action(
        await _crm(authed).request(
            "PATCH", f"{API}/kb/documents/{id}", json=body.model_dump(exclude_none=True)
        )
    )


@router.get(
    "/crm/kb/documents/{id}/chunks", response_model=KbChunkList, operation_id="listKbChunks"
)
async def list_chunks(id: DocumentId, authed: Reader) -> KbChunkList:
    rows = await _crm(authed).get_list(crm.KbChunkOut, f"{API}/kb/documents/{id}/chunks")
    return KbChunkList(items=[KbChunk.model_validate(r.model_dump(mode="json")) for r in rows])


@router.post(
    "/crm/kb/documents/{id}/reingest", response_model=ActionOk, operation_id="reingestKbDocument"
)
async def reingest_document(id: DocumentId, authed: Admin) -> ActionOk:
    return _action(await _crm(authed).request("POST", f"{API}/kb/documents/{id}/reingest"))


# --- поиск и пробелы ----------------------------------------------------------------------------


@router.post("/crm/kb/search", response_model=KbSearchResult, operation_id="searchKb")
async def search(body: KbSearchIn, authed: Reader) -> KbSearchResult:
    out = await _crm(authed).get_model(
        crm.SearchResponse, "POST", f"{API}/kb/search", json=body.model_dump(), probe=True
    )
    return KbSearchResult.model_validate(out.model_dump(mode="json"))


@router.get("/crm/kb/gaps", response_model=KbGapPage, operation_id="listKbGaps")
async def list_gaps(
    authed: Reader,
    gap_status: Annotated[str, Query(alias="status", pattern="^(open|resolved|ignored)$")] = "open",
    language: Language | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> KbGapPage:
    params: dict[str, Any] = {"status": gap_status, "limit": limit, "offset": offset}
    if language is not None:
        params["language"] = language
    out = await _crm(authed).get_model(crm.KbGapPage, "GET", f"{API}/kb/gaps", params=params)
    return KbGapPage(
        items=[KbGap.model_validate(g.model_dump(mode="json")) for g in out.items],
        total=out.total,
    )


@router.post("/crm/kb/gaps/{id}/resolve", response_model=ActionOk, operation_id="resolveKbGap")
async def resolve_gap(id: GapId, body: KbGapResolveIn, authed: Admin) -> ActionOk:
    return _action(
        await _crm(authed).request("POST", f"{API}/kb/gaps/{id}/resolve", json=body.model_dump())
    )


@router.post("/crm/kb/gaps/{id}/ignore", response_model=ActionOk, operation_id="ignoreKbGap")
async def ignore_gap(id: GapId, authed: Admin) -> ActionOk:
    return _action(await _crm(authed).request("POST", f"{API}/kb/gaps/{id}/ignore"))


@router.post("/crm/kb/gaps/{id}/reopen", response_model=ActionOk, operation_id="reopenKbGap")
async def reopen_gap(id: GapId, authed: Admin) -> ActionOk:
    return _action(await _crm(authed).request("POST", f"{API}/kb/gaps/{id}/reopen"))


@router.get("/crm/kb/products", response_model=KbProductList, operation_id="listKbProducts")
async def list_products(authed: Reader) -> KbProductList:
    rows = await _crm(authed).get_list(crm.ProductOut, f"{API}/kb/products")
    return KbProductList(items=[KbProduct.model_validate(r.model_dump(mode="json")) for r in rows])


# --- песочница ----------------------------------------------------------------------------------


@router.post("/crm/sandbox/messages", response_model=SandboxTurn, operation_id="sendSandboxMessage")
async def sandbox_message(body: SandboxMessageIn, authed: Admin) -> SandboxTurn:
    out = await _crm(authed).get_model(
        crm.SandboxTurnOut, "POST", f"{API}/sandbox/messages", json=body.model_dump(), probe=True
    )
    return SandboxTurn.model_validate(out.model_dump(mode="json"))


@router.post(
    "/crm/sandbox/reset", status_code=status.HTTP_204_NO_CONTENT, operation_id="resetSandbox"
)
async def sandbox_reset(authed: Admin) -> Response:
    await _crm(authed).request("POST", f"{API}/sandbox/reset", expected=204)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
