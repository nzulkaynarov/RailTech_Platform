"""Расчёт · Загрузка прайса поставщика (контракт: тег `erp-catalog`; CAT-1, L0-2).

Сотрудник выбирает поставщика, скачивает шаблон, загружает xlsx (или любой файл — строки
предлагает ИИ), видит отчёт проверки и применяет. BFF ничего не решает: поставщика, права
(`catalog.manage`, `supply.manage`, цены поставщиков), правило «чужие карточки не
перезаписываются» и сам отчёт держит ERP (`sourcing/import-catalog[-ai]/`). Файл — как у
техдокументации: тело до 21 МБ копится в памяти BFF (B-D23-6), multipart не разбирается и уходит
в ERP как есть; параметры загрузки идут адресом. Загрузка асинхронная: 202 с номером задачи,
состояние — `GET …/price-import/{job_id}`.

Эталоны: SAP Ariba catalog upload (загрузка → проверка → применение), Odoo «Import vendor
pricelist» (тестовый прогон перед записью), 1С:ERP «Загрузка прайс-листа поставщика» с
сопоставлением номенклатуры.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Query, Request, Response, status
from fastapi.responses import StreamingResponse

from app.api.eds_documents import FileStream
from app.api.erp_catalog import _erp, show_prices
from app.api.erp_docs import _read_limited
from app.clients.erp_company import erp_error
from app.deps import Authed, require
from app.errors import PlatformError
from app.schemas_erp_catalog import (
    ImportMode,
    PriceImportApplyIn,
    PriceImportJob,
    PriceImportStatus,
    to_import_status,
)

router = APIRouter(tags=["erp-catalog"])

Reader = Annotated[Authed, Depends(require("erp.stock", "read"))]
Writer = Annotated[Authed, Depends(require("erp.stock", "full"))]
DateQuery = Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}-\d{2}$")]
JobId = Annotated[str, Path(pattern=r"^[A-Za-z0-9-]{1,64}$")]

_UPLOAD = {"xlsx": "sourcing/import-catalog/", "ai": "sourcing/import-catalog-ai/"}
_STATUS = {"xlsx": "sourcing/import-status/", "ai": "sourcing/ai-status/"}


def _need_prices(authed: Authed) -> None:
    # Прайс несёт цены закупки: загружает тот, кому они открыты (ERP отказал бы так же).
    if not show_prices(authed):
        raise PlatformError(
            "FORBIDDEN",
            "Прайс загружает тот, кому открыты цены поставщиков.",
            status_code=403,
            details={"restricted": "supplier_prices"},
        )


def _job(data: Any, mode: ImportMode) -> PriceImportJob:
    task_id = data.get("task_id") if isinstance(data, dict) else None
    if not isinstance(task_id, str) or not task_id:
        raise PlatformError("BACKEND_UNAVAILABLE", "Загрузка не началась.", status_code=503)
    return PriceImportJob(job_id=task_id, mode=mode)


def _params(**values: Any) -> dict[str, Any]:
    return {k: v for k, v in values.items() if v not in (None, "")}


@router.get(
    "/erp/catalog/price-import/template",
    response_class=StreamingResponse,
    responses={200: {"content": {"application/octet-stream": {}}}},
    operation_id="downloadPriceImportTemplate",
)
async def download_template(authed: Reader) -> Response:
    response = await authed.call("erp", "GET", "/api/v1/sourcing/catalog-template/", stream=True)
    if response.status_code != 200:
        try:
            await response.aread()
            raise erp_error(response)
        finally:
            await response.aclose()
    headers = {
        "Content-Disposition": 'attachment; filename="price-template.xlsx"',
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "private, no-store",
        "Content-Security-Policy": "default-src 'none'; sandbox",
    }
    return FileStream(response, headers, "application/octet-stream")


@router.post(
    "/erp/catalog/price-import",
    response_model=PriceImportJob,
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="startPriceImport",
)
async def start_import(
    request: Request,
    authed: Writer,
    supplier_id: Annotated[str, Query(pattern=r"^[0-9]+$")],
    mode: ImportMode = "xlsx",
    check: bool = True,
    valid_from: DateQuery = None,
    valid_until: DateQuery = None,
) -> PriceImportJob:
    _need_prices(authed)
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
        "POST",
        _UPLOAD[mode],
        params=_params(
            supplier_company_id=supplier_id,
            dry_run="true" if check else "false",
            valid_from=valid_from,
            valid_until=valid_until,
        ),
        content=body,
        content_type=content_type,
    )
    return _job(response.json(), mode)


@router.post(
    "/erp/catalog/price-import/apply-checked",
    response_model=PriceImportJob,
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="applyCheckedPriceImport",
)
async def apply_checked(body: PriceImportApplyIn, authed: Writer) -> PriceImportJob:
    _need_prices(authed)
    response = await _erp(authed).request(
        "POST",
        _UPLOAD["ai"],
        params=_params(
            supplier_company_id=body.supplier_id,
            rows_token=body.rows_token,
            valid_from=body.valid_from,
            valid_until=body.valid_until,
        ),
    )
    return _job(response.json(), "ai")


@router.get(
    "/erp/catalog/price-import/{job_id}",
    response_model=PriceImportStatus,
    operation_id="getPriceImport",
)
async def get_import(job_id: JobId, authed: Reader, mode: ImportMode = "xlsx") -> PriceImportStatus:
    data = await _erp(authed).data("GET", f"{_STATUS[mode]}{job_id}/")
    return to_import_status(data)
