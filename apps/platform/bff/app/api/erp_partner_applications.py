"""Очередь заявок кандидатов в партнёры (PART-ONBOARD-2, ADR-0022).

BFF проксирует к ERP `catalog/partner-applications/` с токеном сотрудника и проверяет раздел
каталога `erp.stock` (чтение — `read`, действия договорного шлюза — `full`).
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query

from app.clients.erp_company import ErpCompany
from app.deps import Authed, require
from app.schemas_partner_applications import (
    PartnerApplicationApproveRequest,
    PartnerApplicationItem,
    PartnerApplicationListResponse,
    PartnerApplicationRejectRequest,
    PartnerApplicationSendContractRequest,
    to_partner_application,
    to_partner_applications_list,
)

router = APIRouter(tags=["erp-catalog"])

Reader = Annotated[Authed, Depends(require("erp.stock", "read"))]
Writer = Annotated[Authed, Depends(require("erp.stock", "full"))]
ApplicationId = Annotated[str, Path(pattern=r"^[0-9]+$")]


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
    status: str = Query(default="", pattern=r"^(|submitted|contract_sent|approved|rejected)$"),
) -> PartnerApplicationListResponse:
    params = {"status": status} if status else {}
    raw = await _erp(authed).data("GET", "catalog/partner-applications/", params=params)
    return to_partner_applications_list(raw)


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
