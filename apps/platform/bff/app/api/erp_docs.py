"""Расчёт · Техдокументация (контракт: тег `erp-catalog`, 0.25.0; D2-3, B-019 часть «ERP ·
Документация»).

BFF проксирует к ERP `catalog/tech-docs/` с токеном сотрудника и проверяет раздел `erp.stock`
(чтение — `read`, загрузка и удаление — `full`; право `catalog.manage` решает ERP). Загрузка: тело
читается потоком до предела (21 МБ), multipart BFF не разбирает и передаёт ERP как есть; файл —
потоком, в памяти BFF не накапливается. Файл всегда отдаётся вложением с `nosniff`: просмотр PDF и
изображений собирает интерфейс сам из полученных байт (CSP Платформы запрещает встроенные
просмотрщики). «Отправить клиенту в чат» в этом разделе нет — чатов ещё нет (B-019, D3)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request, Response, status
from fastapi.responses import StreamingResponse

from app.api.eds_documents import FileStream
from app.api.eds_documents import deal_options as eds_deal_options
from app.api.erp_catalog import Page, PageSize, Search, _erp, _params
from app.clients.erp_company import erp_error
from app.deps import Authed, require
from app.errors import PlatformError
from app.schemas_eds_documents import EdsDealOptions
from app.schemas_erp_catalog import TechDoc, TechDocPage, to_tech_doc, to_tech_page

router = APIRouter(tags=["erp-catalog"])

Reader = Annotated[Authed, Depends(require("erp.stock", "read"))]
Writer = Annotated[Authed, Depends(require("erp.stock", "full"))]
DocId = Annotated[str, Path(pattern=r"^[0-9]+$")]
ID_QUERY = Query(pattern=r"^[0-9]+$")

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_BODY_BYTES = MAX_UPLOAD_BYTES + 1024 * 1024  # поля формы и границы multipart


def _too_large() -> PlatformError:
    return PlatformError(
        "PAYLOAD_TOO_LARGE",
        "Файл больше 20 МБ.",
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


@router.get("/erp/docs/files", response_model=TechDocPage, operation_id="listTechDocs")
async def list_files(
    authed: Reader,
    q: Search = None,
    kind: Annotated[str | None, Query(pattern=r"^(tz|drawing|certificate|pnr|other)$")] = None,
    product_id: Annotated[str | None, ID_QUERY] = None,
    deal_id: Annotated[str | None, ID_QUERY] = None,
    page: Page = 1,
    page_size: PageSize = 25,
) -> TechDocPage:
    data = await _erp(authed).data(
        "GET",
        "catalog/tech-docs/",
        params=_params(
            q=q, kind=kind, product=product_id, deal=deal_id, page=page, page_size=page_size
        ),
    )
    return to_tech_page(data, page, page_size)


@router.post(
    "/erp/docs/files",
    response_model=TechDoc,
    status_code=status.HTTP_201_CREATED,
    operation_id="uploadTechDoc",
)
async def upload_file(request: Request, authed: Writer) -> TechDoc:
    content_type = request.headers.get("content-type", "")
    if not content_type.lower().startswith("multipart/form-data"):
        raise PlatformError(
            "VALIDATION_FAILED",
            "Файл нужно передать формой multipart.",
            status_code=422,
            details={"fields": ["file"], "reason": "multipart_required"},
        )
    body = await _read_limited(request)
    response = await _erp(authed).request(
        "POST", "catalog/tech-docs/", content=body, content_type=content_type
    )
    return to_tech_doc(response.json())


@router.delete(
    "/erp/docs/files/{id}", status_code=status.HTTP_204_NO_CONTENT, operation_id="deleteTechDoc"
)
async def delete_file(id: DocId, authed: Writer) -> Response:
    await _erp(authed).request("DELETE", f"catalog/tech-docs/{id}/")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/erp/docs/files/{id}/content",
    response_class=StreamingResponse,
    responses={200: {"content": {"application/octet-stream": {}}}},
    operation_id="downloadTechDoc",
)
async def download_file(id: DocId, authed: Reader) -> Response:
    response = await authed.call(
        "erp", "GET", f"/api/v1/catalog/tech-docs/{id}/file/", params={"download": "1"}, stream=True
    )
    if response.status_code != 200:
        try:
            await response.aread()
            raise erp_error(response)
        finally:
            await response.aclose()
    disposition = response.headers.get("content-disposition") or "attachment"
    if disposition.lower().startswith("inline"):
        disposition = "attachment" + disposition[len("inline") :]
    headers = {
        "Content-Disposition": disposition,
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "private, no-store",
    }
    return FileStream(response, headers, "application/octet-stream")


@router.get("/erp/docs/deals", response_model=EdsDealOptions, operation_id="listTechDocDealOptions")
async def deal_options(
    authed: Reader, q: Annotated[str | None, Query(max_length=100)] = None
) -> EdsDealOptions:
    return await eds_deal_options(authed, q)
