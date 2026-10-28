"""EDS · Счета и оплаты бухгалтера (контракт: tag `eds-payments`, 0.26.0; D2-4).

Счета, платёжки клиентов и подтверждение оплаты — ERP (`/finance/receivables/*`, права
`finance.invoice` и `finance.payment`
решает ERP); служебки к оплате и «Оплачено» — EDS (`payments.confirm`, шаг «Бухгалтер»). BFF
проверяет раздел каталога
`eds.payments` (чтение — менеджер, директор; действия — бухгалтер), вызывает домены токенами
сотрудника, собирает строки и
карточки и переводит ошибки доменов в формат `Error`. Повторное «Подтвердить оплату» с тем же
`Idempotency-Key` ERP отдаёт
прежним ответом; остаток и «сумма больше остатка» считает ERP.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Path, Query, Request, Response, status
from fastapi.responses import StreamingResponse

from app.api.eds_documents import FileStream, _read_limited
from app.deps import Authed, require
from app.eds_documents import API, EdsProxy
from app.eds_payments import (
    Receivables,
    build_board,
    card_of,
    load_memo,
    memo_card,
    memo_page,
    payments_error,
)
from app.errors import PlatformError
from app.schemas_eds_documents import EdsFile
from app.schemas_eds_payments import (
    InvoiceTab,
    MemoPayStatus,
    PaymentBoard,
    PaymentCard,
    PaymentConfirmIn,
    PaymentMemoCard,
    PaymentMemoPage,
    PaymentMemoPayIn,
)

router = APIRouter(prefix="/eds", tags=["eds-payments"])

Reader = Annotated[Authed, Depends(require("eds.payments", "read"))]
Writer = Annotated[Authed, Depends(require("eds.payments", "full"))]
InvoiceId = Annotated[int, Path(ge=1)]
ProofId = Annotated[int, Path(ge=1)]
MemoId = Annotated[UUID, Path()]
IdemKey = Annotated[str | None, Header(alias="Idempotency-Key", min_length=8, max_length=128)]


def _proxy(authed: Authed) -> EdsProxy:
    return EdsProxy(authed.call)


def _multipart(request: Request) -> str:
    content_type = request.headers.get("content-type", "")
    if not content_type.lower().startswith("multipart/form-data"):
        raise PlatformError(
            "VALIDATION_FAILED",
            "Файл нужно передать формой multipart.",
            status_code=422,
            details={"fields": ["file"], "reason": "multipart_required"},
        )
    return content_type


# --- служебки к оплате (EDS)
# --------------------------------------------------------------------------
# Маршруты `memos/*` объявлены раньше `{id}`: путь счёта — целое число, но порядок держит их
# независимыми.


@router.get("/payment-memos", response_model=PaymentMemoPage, operation_id="listPaymentMemos")
async def list_memos(
    authed: Reader,
    pay_status: Annotated[MemoPayStatus, Query(alias="status")] = "to_pay",
    cursor: Annotated[str | None, Query(max_length=2000)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> PaymentMemoPage:
    params: dict[str, str | int] = {
        "kind": "memo",
        "status": "to_accountant" if pay_status == "to_pay" else "paid",
        "limit": limit,
    }
    if cursor:
        params["cursor"] = cursor
    return memo_page(await _proxy(authed).request("GET", f"{API}/documents", params=params))


@router.get("/payment-memos/{id}", response_model=PaymentMemoCard, operation_id="getPaymentMemo")
async def get_memo(id: MemoId, authed: Reader) -> PaymentMemoCard:
    return await load_memo(_proxy(authed), str(id))


@router.post(
    "/payment-memos/{id}/pay", response_model=PaymentMemoCard, operation_id="payPaymentMemo"
)
async def pay_memo(id: MemoId, body: PaymentMemoPayIn, authed: Writer) -> PaymentMemoCard:
    proxy = _proxy(authed)
    payload = {
        "paid_on": body.paid_on.isoformat(),
        "amount": {"amount": body.amount, "currency": body.currency},
        "receipt_file_id": body.receipt_file_id,
        "note": body.note,
    }
    paid = await proxy.request("POST", f"{API}/documents/{id}/payment", json=payload)
    return memo_card(paid, None)


@router.post(
    "/payment-receipt-files",
    response_model=EdsFile,
    status_code=status.HTTP_201_CREATED,
    operation_id="uploadPaymentReceiptFile",
)
async def upload_receipt(request: Request, authed: Writer) -> EdsFile:
    content_type = _multipart(request)
    body = await _read_limited(request)
    return await _proxy(authed).model(
        EdsFile, "POST", f"{API}/files", expected=201, content=body, content_type=content_type
    )


# --- счета и оплаты (ERP)
# -----------------------------------------------------------------------------


@router.get("/payments", response_model=PaymentBoard, operation_id="listPayments")
async def list_payments(
    authed: Reader,
    tab: InvoiceTab = "awaiting",
    q: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=100000)] = 0,
) -> PaymentBoard:
    return await build_board(authed, tab=tab, q=q, limit=limit, offset=offset)


@router.get("/payments/{id}", response_model=PaymentCard, operation_id="getPayment")
async def get_payment(id: InvoiceId, authed: Reader) -> PaymentCard:
    return card_of(await Receivables(authed).card(id))


@router.post("/payments/{id}/confirm", response_model=PaymentCard, operation_id="confirmPayment")
async def confirm_payment(
    id: InvoiceId, body: PaymentConfirmIn, authed: Writer, idempotency_key: IdemKey = None
) -> PaymentCard:
    payload = {
        "amount": body.amount,
        "paid_at": body.date.isoformat(),
        "reference": body.reference or "",
        "confirmation_id": body.proof_id,
    }
    return card_of(await Receivables(authed).confirm(id, payload, idempotency_key))


@router.post(
    "/payments/{id}/proofs",
    response_model=PaymentCard,
    status_code=status.HTTP_201_CREATED,
    operation_id="attachPaymentProof",
)
async def attach_proof(id: InvoiceId, request: Request, authed: Writer) -> PaymentCard:
    content_type = _multipart(request)
    body = await _read_limited(request)
    return card_of(await Receivables(authed).attach_proof(id, body, content_type))


@router.get(
    "/payments/{id}/proofs/{proof_id}/file",
    response_class=StreamingResponse,
    responses={200: {"content": {"application/octet-stream": {}}}},
    operation_id="downloadPaymentProof",
)
async def download_proof(id: InvoiceId, proof_id: ProofId, authed: Reader) -> Response:
    response = await Receivables(authed).proof_file(id, proof_id)
    if response.status_code != 200:
        try:
            await response.aread()
            raise payments_error(response)
        finally:
            await response.aclose()
    disposition = response.headers.get("content-disposition")
    headers = {
        "Content-Disposition": disposition or "attachment",
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "private, no-store",
    }
    return FileStream(response, headers, "application/octet-stream")


@router.post(
    "/payments/{id}/request-payment-doc",
    response_model=PaymentCard,
    operation_id="requestPaymentDoc",
)
async def request_payment_doc(id: InvoiceId, authed: Writer) -> PaymentCard:
    return card_of(await Receivables(authed).request_doc(id))
