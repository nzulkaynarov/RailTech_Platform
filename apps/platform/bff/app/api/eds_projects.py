"""EDS · Проекты: договор, акт, сканы (контракт: tag `eds-projects`, 0.26.0; D2-5).

BFF не решает: проект, статусы, действия и их допустимость, права `contract.manage`,
`contract.sign`, `fulfillment.act`, сигнатуру и размер скана проверяет ERP. Здесь — разделы
каталога (`eds.projects`: чтение видят менеджер, снабженец, гл. инженер, действия — директор и
бухгалтер), адресация по номеру ПР или id сделки, id документа только из карточки проекта,
перевод ошибок ERP в формат `Error`, поток файла и загрузка скана целиком до предела 20 МБ без
разбора multipart.
"""

import re
from typing import Annotated, Literal

import httpx
from fastapi import APIRouter, Depends, Path, Query, Request, Response, status
from fastapi.responses import JSONResponse, StreamingResponse

from app.api.eds_documents import FileStream
from app.deps import Authed, require
from app.eds_projects import ErpProjects, deal_id_of_number, project_error
from app.errors import PlatformError
from app.schemas_eds_projects import (
    ActActionIn,
    ContractActionIn,
    FileGenerating,
    FileKind,
    FileVariant,
    ProjectCard,
    ProjectPage,
    ProjectStage,
)

router = APIRouter(prefix="/eds", tags=["eds-projects"])

Reader = Annotated[Authed, Depends(require("eds.projects", "read"))]
Writer = Annotated[Authed, Depends(require("eds.projects", "full"))]
Ref = Annotated[str, Path(min_length=1, max_length=64)]

MAX_SCAN_BYTES = 20 * 1024 * 1024
# Файл до 20 МБ плюс поля формы и границы multipart.
MAX_BODY_BYTES = MAX_SCAN_BYTES + 64 * 1024


def _erp(authed: Authed) -> ErpProjects:
    return ErpProjects(authed.call)


def _too_large() -> PlatformError:
    return PlatformError(
        "PAYLOAD_TOO_LARGE",
        "Скан больше 20 МБ.",
        status_code=413,
        details={"max_bytes": MAX_SCAN_BYTES},
    )


async def _scan_body(request: Request) -> tuple[bytes, str]:
    """Тело скана целиком до предела; multipart не разбирается, тип и сигнатуру смотрит ERP."""
    content_type = request.headers.get("content-type", "")
    if not content_type.lower().startswith("multipart/form-data"):
        raise PlatformError(
            "VALIDATION_FAILED",
            "Скан нужно передать формой multipart.",
            status_code=422,
            details={"fields": ["file"], "reason": "multipart_required"},
        )
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        raise _too_large()
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_BODY_BYTES:
            raise _too_large()
    return bytes(body), content_type


_SAFE_EXTENSIONS = frozenset({"pdf", "jpg", "jpeg", "png", "webp"})


def _attachment_name(kind: str, doc_id: int, variant: str, upstream: httpx.Headers) -> str:
    """`attachment; filename="contract-12-scan.pdf"`; расширение — из белого списка."""
    given = upstream.get("content-disposition") or ""
    found = re.search(r'filename\*?=(?:UTF-8\'\')?"?[^";]*\.([A-Za-z0-9]{2,5})"?\s*(?:;|$)', given)
    ext = found.group(1).lower() if found else ""
    if ext not in _SAFE_EXTENSIONS:
        ext = "pdf" if variant == "pdf" else ""
    name = f"{kind}-{doc_id}-{variant}" + (f".{ext}" if ext else "")
    return f'attachment; filename="{name}"'


# --- список и карточка -------------------------------------------------------------------------


@router.get("/projects", response_model=ProjectPage, operation_id="listEdsProjects")
async def list_projects(
    authed: Reader,
    mine: bool = False,
    problems: bool = False,
    step: ProjectStage | None = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0, le=100000)] = 0,
) -> ProjectPage:
    params: dict[str, str | int] = {"limit": limit, "offset": offset}
    if mine:
        params["mine"] = "true"
    if problems:
        params["problems"] = "true"
    if step:
        params["step"] = step
    text = (q or "").strip()
    if text:
        deal_id = deal_id_of_number(text)  # номер ПР или ЗВ: точный поиск сделки
        if deal_id is not None:
            params["deal_id"] = deal_id
        else:
            params["q"] = text
    return await _erp(authed).page(params)


@router.get("/projects/{ref}", response_model=ProjectCard, operation_id="getEdsProject")
async def get_project(ref: Ref, authed: Reader) -> ProjectCard:
    return await _erp(authed).card(ref)


# --- договор -----------------------------------------------------------------------------------


@router.post(
    "/projects/{ref}/contract/draft",
    response_model=ProjectCard,
    status_code=status.HTTP_201_CREATED,
    operation_id="createEdsProjectContract",
)
async def create_contract(ref: Ref, authed: Writer) -> ProjectCard:
    return await _erp(authed).create_contract(ref)


@router.post(
    "/projects/{ref}/contract", response_model=ProjectCard, operation_id="actEdsProjectContract"
)
async def contract_action(ref: Ref, body: ContractActionIn, authed: Writer) -> ProjectCard:
    return await _erp(authed).contract_action(ref, body)


@router.post(
    "/projects/{ref}/contract/scan",
    response_model=ProjectCard,
    operation_id="scanEdsProjectContract",
)
async def contract_scan(ref: Ref, request: Request, authed: Writer) -> ProjectCard:
    content, content_type = await _scan_body(request)
    return await _erp(authed).contract_scan(ref, content, content_type)


# --- акт ---------------------------------------------------------------------------------------


@router.post("/projects/{ref}/act", response_model=ProjectCard, operation_id="actEdsProjectAct")
async def act_action(ref: Ref, body: ActActionIn, authed: Writer) -> ProjectCard:
    return await _erp(authed).act_action(ref, body)


@router.post(
    "/projects/{ref}/act/scan", response_model=ProjectCard, operation_id="scanEdsProjectAct"
)
async def act_scan(ref: Ref, request: Request, authed: Writer) -> ProjectCard:
    content, content_type = await _scan_body(request)
    return await _erp(authed).act_scan(ref, content, content_type)


# --- файлы -------------------------------------------------------------------------------------


@router.get(
    "/projects/{ref}/files/{kind}/{doc_id}",
    response_class=StreamingResponse,
    responses={
        200: {"content": {"application/pdf": {}, "application/octet-stream": {}}},
        202: {"model": FileGenerating},
    },
    operation_id="downloadEdsProjectFile",
)
async def download_file(
    ref: Ref,
    kind: FileKind,
    doc_id: Annotated[int, Path(ge=1, le=2**31 - 1)],
    authed: Reader,
    variant: Literal["pdf", "scan"] = "pdf",
) -> Response:
    variant_: FileVariant = variant
    erp = _erp(authed)
    path = await erp.file_path(ref, kind, doc_id, variant_)
    upstream = await authed.call("erp", "GET", path, stream=True)
    if upstream.status_code == 202:
        try:
            await upstream.aread()
            retry = int(upstream.headers.get("retry-after", "2") or 2)
        finally:
            await upstream.aclose()
        return JSONResponse(
            {"detail": "GENERATING", "retry_after": retry},
            status_code=202,
            headers={"Retry-After": str(retry), "Cache-Control": "no-store"},
        )
    if upstream.status_code != 200:
        try:
            await upstream.aread()
            raise project_error(upstream)
        finally:
            await upstream.aclose()
    # Скан загрузил человек: тип не доверяется, файл скачивается, а не открывается.
    # Имя — своё (вид, id, вариант, расширение из белого списка), не из ответа ERP;
    # содержимое не исполняется: `sandbox`.
    headers = {
        "Content-Disposition": _attachment_name(kind, doc_id, variant_, upstream.headers),
        "Content-Security-Policy": "default-src 'none'; sandbox",
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "private, no-store",
    }
    media = "application/pdf" if variant_ == "pdf" else "application/octet-stream"
    return FileStream(upstream, headers, media)
