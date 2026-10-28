"""EDS · Создать документ и «Мои документы» (контракт: tag `eds-documents`, 0.17.0; D1-5).

BFF проксирует к EDS с токеном доступа сотрудника (обмен SSO-токена CRM `aud=eds`, `app.auth`):
список («Мои» —
`GET /documents?mine=1`, «Все» — `GET /registry`), карточка с шагами маршрута, создание и сохранение
документа с
отправкой на согласование, вложения и поиск заявки для поля «Связь с проектом». Право на тип
документа, номера, маршрут
и видимость решает EDS. Загрузка файла: BFF читает тело потоком до предела (25 МБ и поля формы),
multipart не разбирает
и передаёт EDS как есть; скачивание — потоком, файл в памяти BFF не накапливается.
"""

from collections.abc import AsyncIterator
from typing import Annotated, Any, Literal
from uuid import UUID

import anyio
import httpx
from fastapi import APIRouter, Depends, Header, Path, Query, Request, Response, status
from fastapi.responses import StreamingResponse
from starlette.types import Send

from app.deps import Authed, Rule, require, require_any
from app.eds_documents import (
    API,
    EdsProxy,
    documents_page,
    eds_error,
    present,
    registry_page,
)
from app.errors import PlatformError
from app.feeds.feed import SNAPSHOT_TTL_SECONDS, Feed, rows
from app.feeds.numbers import (
    cyrillic_prefix,
    deal_number,
    deal_title,
    number_query,
)
from app.feeds.snapshot import DEALS_PARAMS, DEALS_PATH
from app.rbac import allows
from app.schemas_eds_documents import (
    DOCUMENT_KINDS,
    EdsDealOption,
    EdsDealOptions,
    EdsDocument,
    EdsDocumentIn,
    EdsDocumentPage,
    EdsDocumentUpdateIn,
    EdsFile,
    RegistryKind,
    StatusFilter,
)

router = APIRouter(tags=["eds-documents"])

MAX_UPLOAD_BYTES = 25 * 1024 * 1024
# Файл до 25 МБ плюс поля формы и границы multipart.
MAX_BODY_BYTES = MAX_UPLOAD_BYTES + 64 * 1024
DEAL_OPTIONS_LIMIT = 10

# Раздел «Документы» открывают все разделы EDS (как пункт меню `documents` каталога).
_EDS_READ: tuple[Rule, ...] = (
    ("eds.memo.create", "read"),
    ("eds.memo.approve", "read"),
    ("eds.inbox", "read"),
    ("eds.drafts", "read"),
    ("eds.projects", "read"),
    ("eds.payments", "read"),
)
# Реестр «Все документы» в EDS — право `registry.read`: его даёт чтение входящих, проектов и
# платежей.
_REGISTRY: tuple[Rule, ...] = (
    ("eds.inbox", "read"),
    ("eds.projects", "read"),
    ("eds.payments", "read"),
)

Reader = Annotated[Authed, Depends(require_any(*_EDS_READ))]
Writer = Annotated[Authed, Depends(require("eds.memo.create", "full"))]
DealReader = Annotated[
    Authed, Depends(require_any(("crm.clients", "read"), ("eds.projects", "read")))
]
DocumentId = Annotated[UUID, Path()]
FileId = Annotated[UUID, Path()]


def _proxy(authed: Authed) -> EdsProxy:
    return EdsProxy(authed.call)


# --- список ---------------------------------------------------------------------------------------


@router.get("/eds/documents", response_model=EdsDocumentPage, operation_id="listEdsDocuments")
async def list_documents(
    authed: Reader,
    scope: Literal["mine", "all"] = "mine",
    kind: Annotated[list[RegistryKind] | None, Query(max_length=9)] = None,
    doc_status: Annotated[list[StatusFilter] | None, Query(alias="status", max_length=10)] = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    cursor: Annotated[str | None, Query(max_length=2000)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> EdsDocumentPage:
    proxy = _proxy(authed)
    params: dict[str, Any] = {"limit": limit}
    if cursor:
        params["cursor"] = cursor
    if doc_status:
        params["status"] = doc_status
    if scope == "all":
        if not any(allows(authed.access, res, need) for res, need in _REGISTRY):
            raise PlatformError(
                "FORBIDDEN",
                "Реестр всех документов не положен вашей роли.",
                status_code=403,
                details={"resource": "eds.inbox", "need": "read"},
            )
        if kind:
            params["kind"] = kind
        if q:
            params["q"] = q
        return registry_page(await proxy.request("GET", f"{API}/registry", params=params))
    kinds = [k for k in (kind or []) if k in DOCUMENT_KINDS]
    if kind and not kinds:
        return EdsDocumentPage(items=[], next_cursor=None)
    if kinds:
        params["kind"] = kinds
    params["mine"] = "true"
    return documents_page(await proxy.request("GET", f"{API}/documents", params=params))


# --- карточка, создание, сохранение ------------------------------------------------------------


@router.get("/eds/documents/{id}", response_model=EdsDocument, operation_id="getEdsDocument")
async def get_document(id: DocumentId, authed: Reader) -> EdsDocument:
    proxy = _proxy(authed)
    body = await proxy.request("GET", f"{API}/documents/{id}")
    return await present(proxy, body, me=authed.data.user_id)


def _with_document(error: PlatformError, document_id: str, *, created: bool) -> PlatformError:
    """
    Документ уже сохранён, а следующий шаг отклонён: экран продолжает с этим документом, введённое
    не теряется.
    """
    error.body.details = {
        **(error.body.details or {}),
        "document_id": document_id,
        "saved": True,
        "created": created,
    }
    return error


def _edits(body: EdsDocumentIn | EdsDocumentUpdateIn) -> dict[str, Any]:
    edits: dict[str, Any] = {
        "subject": body.subject,
        "text": body.text,
        "amount": body.amount.model_dump() if body.amount else None,
        "due_date": body.due_date.isoformat() if body.due_date else None,
        "file_ids": body.file_ids,
        "erp_deal_id": body.erp_deal_id,
    }
    if body.recipient is not None:
        edits["recipient"] = body.recipient.model_dump()
    return edits


async def _submit(proxy: EdsProxy, document_id: str) -> Any:
    return await proxy.request("POST", f"{API}/documents/{document_id}/submit")


@router.post(
    "/eds/documents",
    response_model=EdsDocument,
    status_code=status.HTTP_201_CREATED,
    operation_id="createEdsDocument",
)
async def create_document(
    body: EdsDocumentIn,
    authed: Writer,
    idempotency_key: Annotated[
        str | None, Header(alias="Idempotency-Key", min_length=8, max_length=128)
    ] = None,
) -> EdsDocument:
    proxy = _proxy(authed)
    payload = {"kind": body.kind, **_edits(body)}
    # Повтор с тем же ключом и телом (ответ потерялся): EDS отдаёт прежний документ, а не второй.
    headers = {"Idempotency-Key": idempotency_key} if idempotency_key else None
    created = await proxy.request(
        "POST", f"{API}/documents", expected=201, json=payload, headers=headers
    )
    result = created
    if body.submit:
        document_id = str(created.get("id", ""))
        try:
            result = await _submit(proxy, document_id)
        except PlatformError as exc:
            raise _with_document(exc, document_id, created=True) from exc
    return await present(proxy, result, me=authed.data.user_id)


@router.put("/eds/documents/{id}", response_model=EdsDocument, operation_id="updateEdsDocument")
async def update_document(id: DocumentId, body: EdsDocumentUpdateIn, authed: Writer) -> EdsDocument:
    proxy = _proxy(authed)
    saved = await proxy.request("PATCH", f"{API}/documents/{id}", json=_edits(body))
    result = saved
    if body.submit:
        try:
            result = await _submit(proxy, str(id))
        except PlatformError as exc:
            raise _with_document(exc, str(id), created=False) from exc
    return await present(proxy, result, me=authed.data.user_id)


# --- вложения -------------------------------------------------------------------------------------


def _too_large() -> PlatformError:
    return PlatformError(
        "PAYLOAD_TOO_LARGE",
        "Файл больше 25 МБ.",
        status_code=413,
        details={"max_bytes": MAX_UPLOAD_BYTES},
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
    "/eds/document-files",
    response_model=EdsFile,
    status_code=status.HTTP_201_CREATED,
    operation_id="uploadEdsDocumentFile",
)
async def upload_file(request: Request, authed: Writer) -> EdsFile:
    content_type = request.headers.get("content-type", "")
    if not content_type.lower().startswith("multipart/form-data"):
        raise PlatformError(
            "VALIDATION_FAILED",
            "Файл нужно передать формой multipart.",
            status_code=422,
            details={"fields": ["file"], "reason": "multipart_required"},
        )
    body = await _read_limited(request)
    return await _proxy(authed).model(
        EdsFile,
        "POST",
        f"{API}/files",
        expected=201,
        content=body,
        content_type=content_type,
    )


async def _relay(response: httpx.Response) -> AsyncIterator[bytes]:
    async for chunk in response.aiter_bytes():
        yield chunk


class FileStream(StreamingResponse):
    """
    Файл потоком; ответ EDS закрывается всегда — файл отдан, клиент оборвал загрузку, EDS оборвал
    поток.
    """

    def __init__(self, upstream: httpx.Response, headers: dict[str, str], media_type: str) -> None:
        super().__init__(_relay(upstream), media_type=media_type, headers=headers)
        self._upstream = upstream

    async def stream_response(self, send: Send) -> None:
        try:
            await super().stream_response(send)
        finally:
            with anyio.CancelScope(shield=True):
                await self._upstream.aclose()


@router.get(
    "/eds/document-files/{file_id}",
    response_class=StreamingResponse,
    responses={200: {"content": {"application/octet-stream": {}}}},
    operation_id="downloadEdsDocumentFile",
)
async def download_file(file_id: FileId, authed: Reader) -> Response:
    response = await _proxy(authed).raw("GET", f"{API}/files/{file_id}", stream=True)
    if response.status_code != 200:
        try:
            await response.aread()
            raise eds_error(response)
        finally:
            await response.aclose()
    disposition = response.headers.get("content-disposition")
    headers = {
        "Content-Disposition": disposition or "attachment",
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "private, no-store",
    }
    # Тип содержимого не доверяется: файл всегда скачивается (attachment), а не исполняется во
    # вкладке.
    return FileStream(response, headers, "application/octet-stream")


# --- связь с проектом -----------------------------------------------------------------------------


def _matches(deal: dict[str, Any], needles: tuple[str, ...]) -> bool:
    haystack = (
        deal_number(deal),
        str(deal.get("title") or ""),
        str(deal.get("company_name") or ""),
    )
    return any(needle in part.casefold() for part in haystack for needle in needles)


@router.get("/eds/deal-options", response_model=EdsDealOptions, operation_id="listEdsDealOptions")
async def deal_options(
    authed: DealReader, q: Annotated[str | None, Query(max_length=100)] = None
) -> EdsDealOptions:
    feed = Feed(authed)
    payload = await feed.get("erp", DEALS_PATH, DEALS_PARAMS, ttl=SNAPSHOT_TTL_SECONDS)
    deals = sorted(
        (d for d in rows(payload) if isinstance(d.get("id"), int)),
        key=lambda d: int(d["id"]),
        reverse=True,
    )
    text = (q or "").strip()
    if text:
        # Запрос как набран, с кириллическим префиксом номера и в каноническом виде `ЗВ-2026-001`.
        needles = tuple(
            dict.fromkeys(
                n.casefold() for n in (text, cyrillic_prefix(text), number_query(text)) if n
            )
        )
        deals = [d for d in deals if _matches(d, needles)]
    items = [
        EdsDealOption(
            erp_deal_id=int(d["id"]),
            number=deal_number(d),
            title=deal_title(d),
            company=str(d["company_name"]) if d.get("company_name") else None,
        )
        for d in deals[:DEAL_OPTIONS_LIMIT]
    ]
    return EdsDealOptions(items=items, sources=feed.sources)
