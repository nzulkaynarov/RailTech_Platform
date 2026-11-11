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

from app.clients.eds import EdsLetters
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
    deal_number,
    deal_title,
)
from app.feeds.rework import drop_returned
from app.feeds.snapshot import DEALS_PARAMS, DEALS_PATH
from app.rbac import allows
from app.schemas_eds_documents import (
    DOCUMENT_KINDS,
    DOCUMENT_STATUSES,
    EdsDealOption,
    EdsDealOptions,
    EdsDocument,
    EdsDocumentIn,
    EdsDocumentPage,
    EdsDocumentPdf,
    EdsDocumentSignIn,
    EdsDocumentUpdateIn,
    EdsFile,
    EdsLetterhead,
    RegistryKind,
    StatusFilter,
)
from app.schemas_eds_letters import NUMBER_RE

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
# Регистрация исходящих и «Отправить адресату» (P4): раздел регистрации входящих и исходящих.
Registrar = Annotated[Authed, Depends(require("eds.inbox.register", "full"))]
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
    if scope == "all":
        if doc_status:
            params["status"] = doc_status
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
    statuses = [s for s in (doc_status or []) if s in DOCUMENT_STATUSES]
    if doc_status and not statuses:
        return EdsDocumentPage(items=[], next_cursor=None)
    if statuses:
        params["status"] = statuses
    params["mine"] = "true"
    return documents_page(await proxy.request("GET", f"{API}/documents", params=params))


# --- карточка, создание, сохранение ------------------------------------------------------------


@router.get("/eds/documents/{id}", response_model=EdsDocument, operation_id="getEdsDocument")
async def get_document(id: DocumentId, authed: Reader) -> EdsDocument:
    proxy = _proxy(authed)
    body = await proxy.request("GET", f"{API}/documents/{id}")
    return await _present(proxy, body, authed)


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
    if body.letter is not None:
        edits["letter"] = body.letter.model_dump(exclude_none=True)
    return edits


def _registrar(authed: Authed) -> bool:
    return allows(authed.access, "eds.inbox.register", "full")


async def _present(
    proxy: EdsProxy, body: Any, authed: Authed, *, registrar: bool | None = None
) -> EdsDocument:
    return await present(
        proxy,
        body,
        me=authed.data.user_id,
        registrar=_registrar(authed) if registrar is None else registrar,
        inbox=_inbox(authed),
    )


def _inbox(authed: Authed) -> bool:
    """Есть раздел «Входящие» (чтение или регистрация): «В ответ на ВХ» ведёт в карточку письма."""
    return allows(authed.access, "eds.inbox", "read") or allows(
        authed.access, "eds.inbox.register", "read"
    )


def _bad_reply_to(reason: str) -> PlatformError:
    return PlatformError(
        "VALIDATION_FAILED",
        "Входящее письмо с таким номером не найдено."
        if reason == "not_found"
        else "«В ответ на ВХ» — только у письма.",
        status_code=422,
        details={"fields": ["in_reply_to_number"], "reason": reason},
    )


async def _letter_id(authed: Authed, kind: str, number: str) -> str:
    """«В ответ на ВХ» (P8b): id входящего по номеру; поручения «ответить» закрывает EDS."""
    if kind != "letter_out":
        raise _bad_reply_to("letter_out_only")
    if not NUMBER_RE.match(number):
        raise _bad_reply_to("not_found")
    found = await EdsLetters(authed.call).id_by_number(number)
    if found is None:
        raise _bad_reply_to("not_found")
    return found


async def _submit(proxy: EdsProxy, document_id: str, *, send: bool = False) -> Any:
    # P4: письмо на бланке после регистрации уходит адресату почтой (`send`); без флага — тело
    # запроса не нужно.
    payload = {"send": True} if send else None
    return await proxy.request("POST", f"{API}/documents/{document_id}/submit", json=payload)


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
    reply_to = (body.in_reply_to_number or "").strip()
    if reply_to:
        payload["in_reply_to"] = await _letter_id(authed, body.kind, reply_to)
    # Повтор с тем же ключом и телом (ответ потерялся): EDS отдаёт прежний документ, а не второй.
    headers = {"Idempotency-Key": idempotency_key} if idempotency_key else None
    created = await proxy.request(
        "POST", f"{API}/documents", expected=201, json=payload, headers=headers
    )
    result = created
    if body.submit:
        document_id = str(created.get("id", ""))
        try:
            result = await _submit(proxy, document_id, send=body.send)
        except PlatformError as exc:
            raise _with_document(exc, document_id, created=True) from exc
    return await _present(proxy, result, authed)


@router.put("/eds/documents/{id}", response_model=EdsDocument, operation_id="updateEdsDocument")
async def update_document(id: DocumentId, body: EdsDocumentUpdateIn, authed: Writer) -> EdsDocument:
    proxy = _proxy(authed)
    saved = await proxy.request("PATCH", f"{API}/documents/{id}", json=_edits(body))
    result = saved
    if body.submit:
        try:
            result = await _submit(proxy, str(id), send=body.send)
        except PlatformError as exc:
            raise _with_document(exc, str(id), created=False) from exc
        # Документ ушёл на согласование — он больше не «Доработать» в очереди автора (D1-6b)
        await drop_returned(Feed(authed))
    return await _present(proxy, result, authed)


# --- письмо на бланке (P4) ------------------------------------------------------------------------


@router.post(
    "/eds/documents/{id}/pdf",
    response_model=EdsDocumentPdf,
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="requestEdsDocumentPdf",
)
async def request_pdf(id: DocumentId, authed: Writer) -> EdsDocumentPdf:
    """PDF строит фоновый воркер EDS; ответ сразу — `pending` или `ready` (кэш по хешу)."""
    return await _proxy(authed).model(
        EdsDocumentPdf, "POST", f"{API}/documents/{id}/pdf", expected=202
    )


@router.get(
    "/eds/documents/{id}/pdf", response_model=EdsDocumentPdf, operation_id="getEdsDocumentPdf"
)
async def get_pdf(id: DocumentId, authed: Reader) -> EdsDocumentPdf:
    return await _proxy(authed).model(EdsDocumentPdf, "GET", f"{API}/documents/{id}/pdf")


@router.get(
    "/eds/documents/{id}/pdf/file",
    response_class=StreamingResponse,
    responses={200: {"content": {"application/pdf": {}}}},
    operation_id="downloadEdsDocumentPdf",
)
async def download_pdf(id: DocumentId, authed: Reader) -> Response:
    """PDF, построенный EDS из узлов контракта (не файл пользователя): `application/pdf`,
    `inline` — для предпросмотра."""
    response = await _proxy(authed).raw("GET", f"{API}/documents/{id}/pdf/file", stream=True)
    if response.status_code != 200:
        try:
            await response.aread()
            raise eds_error(response)
        finally:
            await response.aclose()
    disposition = response.headers.get("content-disposition") or "inline"
    headers = {
        "Content-Disposition": disposition if disposition.startswith("inline") else "inline",
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "private, no-store",
    }
    return FileStream(response, headers, "application/pdf")


@router.post(
    "/eds/documents/{id}/registration-request",
    response_model=EdsDocument,
    operation_id="requestEdsDocumentRegistration",
)
async def request_registration(id: DocumentId, authed: Writer) -> EdsDocument:
    proxy = _proxy(authed)
    body = await proxy.request("POST", f"{API}/documents/{id}/registration-request")
    return await _present(proxy, body, authed)


@router.post("/eds/documents/{id}/send", response_model=EdsDocument, operation_id="sendEdsDocument")
async def send_document(id: DocumentId, authed: Registrar) -> EdsDocument:
    proxy = _proxy(authed)
    body = await proxy.request("POST", f"{API}/documents/{id}/send")
    return await _present(proxy, body, authed, registrar=True)


@router.post(
    "/eds/documents/{id}/sign",
    response_model=EdsDocument,
    operation_id="signEdsDocument",
)
async def sign_document(
    id: DocumentId,
    authed: Reader,
    body: EdsDocumentSignIn | None = None,
) -> EdsDocument:
    proxy = _proxy(authed)
    payload = body.model_dump(exclude_none=True) if body else {}
    data = await proxy.request("POST", f"{API}/documents/{id}/sign", json=payload)
    return await _present(proxy, data, authed)


@router.get("/eds/letterhead", response_model=EdsLetterhead, operation_id="getEdsLetterhead")
async def get_letterhead(authed: Reader) -> EdsLetterhead:
    return await _proxy(authed).model(EdsLetterhead, "GET", f"{API}/letterhead")


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


@router.get("/eds/deal-options", response_model=EdsDealOptions, operation_id="listEdsDealOptions")
async def deal_options(
    authed: DealReader, q: Annotated[str | None, Query(max_length=100)] = None
) -> EdsDealOptions:
    feed = Feed(authed)
    text = (q or "").strip()
    if text:
        # Номер, название и компанию ищет ERP (`?search=`): запрос уходит как набран.
        payload = await feed.get(
            "erp", DEALS_PATH, {"search": text, "page_size": DEAL_OPTIONS_LIMIT}
        )
    else:
        payload = await feed.get("erp", DEALS_PATH, DEALS_PARAMS, ttl=SNAPSHOT_TTL_SECONDS)
    deals = sorted(
        (d for d in rows(payload) if isinstance(d.get("id"), int)),
        key=lambda d: int(d["id"]),
        reverse=True,
    )
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
