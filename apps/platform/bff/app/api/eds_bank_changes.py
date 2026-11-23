"""Счета и оплаты · смена реквизитов контрагента (FX-4, решение владельца 2026-11-08).

BFF не решает: права (`finance.view`, `finance.payment`), маска реквизитов, статусы и повторы —
ERP (`finance/bank-changes/`). Раздел каталога — `eds.payments`: читает директор и менеджер, решает
бухгалтер. Подключается раньше `eds_payments`, иначе `/eds/payments/bank-changes` поймал бы
`/eds/payments/{id}`.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query

from app.clients.crm_users import STEP_UP_HEADER
from app.clients.erp_company import ErpCompany
from app.deps import Authed, StepUpDep, require
from app.errors import from_backend
from app.schemas_bank_changes import (
    BankChangeItem,
    BankChangeList,
    BankChangeRejectRequest,
    BankChangeStatus,
    to_item,
    to_list,
)

router = APIRouter(prefix="/eds/payments/bank-changes", tags=["eds-payments"])

Reader = Annotated[Authed, Depends(require("eds.payments", "read"))]
Writer = Annotated[Authed, Depends(require("eds.payments", "full"))]
ChangeId = Annotated[str, Path(pattern=r"^[0-9]+$")]


def _erp(authed: Authed) -> ErpCompany:
    return ErpCompany(authed.call)


def _path(id: str, tail: str) -> str:
    return f"finance/bank-changes/{id}/{tail}"


@router.get("", response_model=BankChangeList, operation_id="listBankChangeRequests")
async def list_bank_change_requests(
    authed: Reader, status: Annotated[BankChangeStatus | None, Query()] = None
) -> BankChangeList:
    params = {"status": status} if status else {}
    return to_list(await _erp(authed).data("GET", "finance/bank-changes/", params=params))


@router.post(
    "/{id}/approve", response_model=BankChangeItem, operation_id="approveBankChangeRequest"
)
async def approve_bank_change_request(
    id: ChangeId, authed: Writer, step_up: StepUpDep = None
) -> BankChangeItem:
    """Подтвердить новые реквизиты. Нужен свежий код второго фактора (`X-Step-Up-Token`, ДВ-4б):
    проверяет CRM до обращения к ERP; нет кода — 403 `STEP_UP_REQUIRED`."""
    checked = await authed.call(
        "crm",
        "POST",
        "/api/v1/me/second-factor/step-up/check",
        headers={STEP_UP_HEADER: step_up} if step_up else None,
    )
    if checked.status_code != 204:
        raise from_backend("crm", checked)
    return to_item(await _erp(authed).data("POST", _path(id, "approve/")))


@router.post("/{id}/reject", response_model=BankChangeItem, operation_id="rejectBankChangeRequest")
async def reject_bank_change_request(
    id: ChangeId, body: BankChangeRejectRequest, authed: Writer
) -> BankChangeItem:
    raw = await _erp(authed).data("POST", _path(id, "reject/"), json={"reason": body.reason})
    return to_item(raw)
