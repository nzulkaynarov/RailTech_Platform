"""Доступ поставщика в кабинет: блок «Доступ в кабинет» карточки поставщика (контракт BFF, тег
`erp-catalog`; PART-1).

BFF проксирует к ERP `catalog/supplier-access/{id}/` с токеном сотрудника и проверяет раздел
каталога `erp.stock` (чтение — `read`, изменения — `full`). Право на изменения решает ERP
(`supply.manage`); письмо с кодом входа партнёру отправляет ERP тем же механизмом, что клиенту,
ссылки и кода в ответах нет.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, status

from app.clients.erp_company import ErpCompany
from app.deps import Authed, require
from app.schemas_supplier_access import (
    SupplierCabinetAccess,
    SupplierCabinetContact,
    SupplierCabinetContactCreate,
    SupplierCabinetContactUpdate,
    SupplierCabinetInvite,
    SupplierCabinetRightsUpdate,
    invite_to_erp,
    to_access,
    to_contact,
)

router = APIRouter(tags=["erp-catalog"])

Reader = Annotated[Authed, Depends(require("erp.stock", "read"))]
Writer = Annotated[Authed, Depends(require("erp.stock", "full"))]
SupplierId = Annotated[str, Path(pattern=r"^[0-9]+$")]
ContactId = Annotated[str, Path(pattern=r"^[0-9]+$")]


def _erp(authed: Authed) -> ErpCompany:
    return ErpCompany(authed.call)


def _path(id: str, tail: str = "") -> str:
    return f"catalog/supplier-access/{id}/{tail}"


@router.get(
    "/erp/catalog/suppliers/{id}/cabinet-access",
    response_model=SupplierCabinetAccess,
    operation_id="getSupplierCabinetAccess",
)
async def get_access(id: SupplierId, authed: Reader) -> SupplierCabinetAccess:
    return to_access(await _erp(authed).data("GET", _path(id)))


@router.post(
    "/erp/catalog/suppliers/{id}/cabinet-access/contacts",
    response_model=SupplierCabinetContact,
    status_code=status.HTTP_201_CREATED,
    operation_id="createSupplierCabinetContact",
)
async def create_contact(
    id: SupplierId, body: SupplierCabinetContactCreate, authed: Writer
) -> SupplierCabinetContact:
    raw = await _erp(authed).data("POST", _path(id, "contacts/"), json=body.sent())
    return to_contact(raw)


@router.patch(
    "/erp/catalog/suppliers/{id}/cabinet-access/contacts/{contact_id}",
    response_model=SupplierCabinetContact,
    operation_id="updateSupplierCabinetContact",
)
async def update_contact(
    id: SupplierId, contact_id: ContactId, body: SupplierCabinetContactUpdate, authed: Writer
) -> SupplierCabinetContact:
    raw = await _erp(authed).data("PATCH", _path(id, f"contacts/{contact_id}/"), json=body.sent())
    return to_contact(raw)


@router.patch(
    "/erp/catalog/suppliers/{id}/cabinet-access/relationship",
    response_model=SupplierCabinetAccess,
    operation_id="updateSupplierCabinetRights",
)
async def update_rights(
    id: SupplierId, body: SupplierCabinetRightsUpdate, authed: Writer
) -> SupplierCabinetAccess:
    raw = await _erp(authed).data("PATCH", _path(id, "relationship/"), json=body.sent())
    return to_access(raw)


@router.post(
    "/erp/catalog/suppliers/{id}/cabinet-access/invite",
    response_model=SupplierCabinetAccess,
    operation_id="inviteSupplierToCabinet",
)
async def invite(
    id: SupplierId, body: SupplierCabinetInvite, authed: Writer
) -> SupplierCabinetAccess:
    raw = await _erp(authed).data("POST", _path(id, "invite/"), json=invite_to_erp(body.sent()))
    return to_access(raw)


@router.post(
    "/erp/catalog/suppliers/{id}/cabinet-access/suspend",
    response_model=SupplierCabinetAccess,
    operation_id="suspendSupplierCabinetAccess",
)
async def suspend(id: SupplierId, authed: Writer) -> SupplierCabinetAccess:
    return to_access(await _erp(authed).data("POST", _path(id, "suspend/")))


@router.post(
    "/erp/catalog/suppliers/{id}/cabinet-access/crm-client/confirm",
    response_model=SupplierCabinetAccess,
    operation_id="confirmSupplierCrmClient",
)
async def confirm_crm_client(id: SupplierId, authed: Writer) -> SupplierCabinetAccess:
    """«Да, это та же компания» (PART-CRM): сопоставление проверено, заявки уходят."""
    return to_access(await _erp(authed).data("POST", _path(id, "crm-client/confirm/")))


@router.post(
    "/erp/catalog/suppliers/{id}/cabinet-access/crm-client/reject",
    response_model=SupplierCabinetAccess,
    operation_id="rejectSupplierCrmClient",
)
async def reject_crm_client(id: SupplierId, authed: Writer) -> SupplierCabinetAccess:
    """«Нет, другая компания» (PART-CRM): сопоставление снято, CRM получает отказ."""
    return to_access(await _erp(authed).data("POST", _path(id, "crm-client/reject/")))
