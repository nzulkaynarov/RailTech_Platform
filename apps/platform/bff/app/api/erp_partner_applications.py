"""Очередь заявок кандидатов в партнёры (PART-ONBOARD-2, ADR-0022).

BFF проксирует к ERP `catalog/partner-applications/` с токеном сотрудника и проверяет раздел
каталога `erp.stock` (чтение — `read`, действия договорного шлюза — `full`).
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request, Response
from fastapi.responses import StreamingResponse

from app.api.eds_documents import FileStream
from app.api.erp_docs import _read_limited
from app.clients.erp_company import ErpCompany, erp_error
from app.deps import Authed, require, require_any
from app.errors import PlatformError
from app.schemas_partner_applications import (
    PartnerApplicationApproveRequest,
    PartnerApplicationCreateRequest,
    PartnerApplicationInviteRequest,
    PartnerApplicationItem,
    PartnerApplicationListResponse,
    PartnerApplicationRejectRequest,
    PartnerApplicationSendContractRequest,
    PartnerContractDecisionRequest,
    PartnerContractOptions,
    PartnerContractPrepareRequest,
    to_contract_options,
    to_partner_application,
    to_partner_applications_list,
)

router = APIRouter(tags=["erp-catalog"])

# Читает снабжение и держатель зоны «Право» (ему нужен договор для решения); действия — снабжение
Reader = Annotated[Authed, Depends(require_any(("erp.stock", "read"), ("eds.visa.legal", "read")))]
Writer = Annotated[Authed, Depends(require("erp.stock", "full"))]
# Решение по договору — держатель зоны «Право» (как утверждение шаблонов); само право проверяет ERP
Decider = Annotated[Authed, Depends(require_any(("eds.visa.legal", "full"), ("admin", "full")))]
ApplicationId = Annotated[str, Path(pattern=r"^[0-9]+$")]


_EXTENSIONS = {
    "wordprocessingml": "docx",
    "pdf": "pdf",
    "jpeg": "jpg",
    "png": "png",
    "webp": "webp",
}


def _erp(authed: Authed) -> ErpCompany:
    return ErpCompany(authed.call)


def _path(id: str, tail: str = "") -> str:
    return f"catalog/partner-applications/{id}/{tail}"


@router.get(
    "/erp/catalog/partner-applications",
    response_model=PartnerApplicationListResponse,
    operation_id="listPartnerApplications",
)
async def list_partner_applications(
    authed: Reader,
    status: str = Query(
        default="", pattern=r"^(|submitted|contract_sent|candidate_agreed|approved|rejected)$"
    ),
) -> PartnerApplicationListResponse:
    params = {"status": status} if status else {}
    raw = await _erp(authed).data("GET", "catalog/partner-applications/", params=params)
    return to_partner_applications_list(raw)


@router.post(
    "/erp/catalog/partner-applications",
    response_model=PartnerApplicationItem,
    status_code=201,
    operation_id="createPartnerApplication",
)
async def create_partner_application(
    body: PartnerApplicationCreateRequest, authed: Writer
) -> PartnerApplicationItem:
    """План 1.9: заявка кандидата по входящему письму; право решает ERP (`supply.manage`)."""
    raw = await _erp(authed).data("POST", "catalog/partner-applications/", json=body.sent())
    return to_partner_application(raw)


@router.post(
    "/erp/catalog/partner-applications/{id}/send-contract",
    response_model=PartnerApplicationItem,
    operation_id="sendContractPartnerApplication",
)
async def send_contract_partner_application(
    id: ApplicationId,
    authed: Writer,
    body: PartnerApplicationSendContractRequest | None = None,
) -> PartnerApplicationItem:
    json_body = body.sent() if body else {}
    if json_body.get("company_id"):
        json_body["company_id"] = int(json_body["company_id"])
    raw = await _erp(authed).data("POST", _path(id, "send-contract/"), json=json_body)
    return to_partner_application(raw)


@router.post(
    "/erp/catalog/partner-applications/{id}/approve",
    response_model=PartnerApplicationItem,
    operation_id="approvePartnerApplication",
)
async def approve_partner_application(
    id: ApplicationId,
    body: PartnerApplicationApproveRequest,
    authed: Writer,
) -> PartnerApplicationItem:
    sent = body.sent()
    if sent.get("company_id"):
        sent["company_id"] = int(sent["company_id"])
    raw = await _erp(authed).data("POST", _path(id, "approve/"), json=sent)
    return to_partner_application(raw)


@router.post(
    "/erp/catalog/partner-applications/{id}/invite",
    response_model=PartnerApplicationItem,
    operation_id="invitePartnerCandidate",
)
async def invite_candidate(
    id: ApplicationId,
    authed: Writer,
    body: PartnerApplicationInviteRequest | None = None,
) -> PartnerApplicationItem:
    """«Пригласить в Кабинет» позже (ПК-1): договор отправлен без почты, теперь адрес есть."""
    raw = await _erp(authed).data("POST", _path(id, "invite/"), json=body.sent() if body else {})
    return to_partner_application(raw)


@router.post(
    "/erp/catalog/partner-applications/{id}/signed-scan",
    response_model=PartnerApplicationItem,
    operation_id="uploadPartnerSignedScan",
)
async def upload_signed_scan(
    id: ApplicationId, request: Request, authed: Writer
) -> PartnerApplicationItem:
    """Скан подписанного договора по желанию (ПК-1): multipart уходит в ERP как есть."""
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
        "POST", _path(id, "signed-scan/"), content=body, content_type=content_type
    )
    return to_partner_application(response.json())


@router.post(
    "/erp/catalog/partner-applications/{id}/reject",
    response_model=PartnerApplicationItem,
    operation_id="rejectPartnerApplication",
)
async def reject_partner_application(
    id: ApplicationId,
    body: PartnerApplicationRejectRequest,
    authed: Writer,
) -> PartnerApplicationItem:
    raw = await _erp(authed).data("POST", _path(id, "reject/"), json=body.sent())
    return to_partner_application(raw)


@router.get(
    "/erp/catalog/partner-applications/contract-options",
    response_model=PartnerContractOptions,
    operation_id="getPartnerContractOptions",
)
async def contract_options(authed: Reader) -> PartnerContractOptions:
    """Утверждённые партнёрские шаблоны библиотеки, умолчание из настроек и кто решает (ПД-1)."""
    raw = await _erp(authed).data("GET", "catalog/partner-applications/contract-options/")
    return to_contract_options(raw)


@router.post(
    "/erp/catalog/partner-applications/{id}/prepare-contract",
    response_model=PartnerApplicationItem,
    operation_id="preparePartnerContract",
)
async def prepare_contract(
    id: ApplicationId, body: PartnerContractPrepareRequest, authed: Writer
) -> PartnerApplicationItem:
    sent = body.sent()
    if sent.get("template_id"):
        sent["template_id"] = int(sent["template_id"])
    raw = await _erp(authed).data("POST", _path(id, "prepare-contract/"), json=sent)
    return to_partner_application(raw)


@router.post(
    "/erp/catalog/partner-applications/{id}/prepare-contract-file",
    response_model=PartnerApplicationItem,
    operation_id="uploadPartnerContractFile",
)
async def upload_contract_file(
    id: ApplicationId, request: Request, authed: Writer
) -> PartnerApplicationItem:
    """Свой файл договора (PDF или DOCX): multipart уходит в ERP как есть, как у техдокументации."""
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
        "POST", _path(id, "prepare-contract/"), content=body, content_type=content_type
    )
    return to_partner_application(response.json())


@router.post(
    "/erp/catalog/partner-applications/{id}/contract-decision",
    response_model=PartnerApplicationItem,
    operation_id="decidePartnerContract",
)
async def decide_contract(
    id: ApplicationId, body: PartnerContractDecisionRequest, authed: Decider
) -> PartnerApplicationItem:
    """Решение держателя зоны «Право»; право проверяет ERP (`contract.approve_template`)."""
    raw = await _erp(authed).data("POST", _path(id, "contract-decision/"), json=body.sent())
    return to_partner_application(raw)


@router.get(
    "/erp/catalog/partner-applications/{id}/document",
    response_class=StreamingResponse,
    responses={200: {"content": {"application/octet-stream": {}}}},
    operation_id="downloadPartnerApplicationDocument",
)
async def download_document(
    id: ApplicationId,
    authed: Reader,
    which: Annotated[str, Query(pattern=r"^(contract|scan|candidate)$")] = "contract",
) -> Response:
    """Договор, который видит кандидат, или скан подписанного — вложением."""
    response = await authed.call(
        "erp",
        "GET",
        f"/api/v1/{_path(id, 'document/')}",
        params={"which": which},
        stream=True,
    )
    if response.status_code != 200:
        try:
            await response.aread()
            raise erp_error(response)
        finally:
            await response.aclose()
    kind = response.headers.get("content-type", "")
    ext = next(
        (e for key, e in _EXTENSIONS.items() if key in kind), "bin"
    )  # тип приходит от ERP по расширению файла
    headers = {
        "Content-Disposition": f'attachment; filename="partner-{which}-{id}.{ext}"',
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "private, no-store",
        "Content-Security-Policy": "default-src 'none'; sandbox",
    }
    return FileStream(response, headers, "application/octet-stream")
