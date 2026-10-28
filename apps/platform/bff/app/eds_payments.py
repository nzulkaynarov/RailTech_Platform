"""Сборка экрана «Счета и оплаты» бухгалтера (контракт BFF 0.26.0, тег `eds-payments`; D2-4).

BFF не решает: остаток, статус счёта, «просрочен», права на оплату (`finance.payment`) и на чтение
счетов — ERP; шаг «Бухгалтер»
служебной записки, её сумма и разделение обязанностей — EDS. Здесь — вызовы с токеном сотрудника,
сборка строк и карточек в
словаре SPEC-v3 (ПР-номер из года и id сделки до ERP-09), перевод ошибок ERP
(`PAYMENT_EXCEEDS_BALANCE_DUE`, …) в формат `Error`.
"""

import asyncio
import contextlib
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Literal, cast

import httpx
from pydantic import BaseModel, ValidationError

from app.clients.erp_company import erp_error
from app.deps import Authed
from app.eds_documents import API as EDS_API
from app.eds_documents import EdsProxy
from app.errors import PlatformError, backend_unavailable, from_backend
from app.schemas_eds_documents import EdsDealRef, EdsFile, EdsPerson
from app.schemas_eds_payments import (
    InvoiceTab,
    PaymentBoard,
    PaymentCard,
    PaymentCounts,
    PaymentHistoryEntry,
    PaymentItem,
    PaymentMemoCard,
    PaymentMemoJournal,
    PaymentMemoPage,
    PaymentMemoPayment,
    PaymentMemoRow,
    PaymentMoney,
    PaymentProof,
    PaymentRecord,
    PaymentRow,
    PaymentSources,
)

ERP_API = "/api/v1/finance/receivables/"
MEMOS_COUNT_LIMIT = 100
_DEFAULT_CURRENCY = "UZS"

# Отказы ERP, которые для бухгалтера — конфликт с состоянием счёта: код ERP -> (причина, текст).
_CONFLICTS: dict[str, tuple[str, str]] = {
    "PAYMENT_EXCEEDS_BALANCE_DUE": ("exceeds_balance", "Сумма больше остатка по счёту."),
    "INVOICE_ALREADY_PAID": ("already_paid", "Счёт уже оплачен полностью."),
    "INVOICE_NOT_ISSUED": (
        "not_issued",
        "Счёт ещё не выставлен: оплату можно подтвердить только по выставленному счёту.",
    ),
    "INVOICE_NOT_OPEN": ("not_open", "Счёт не ждёт оплаты: он оплачен, отменён или не выставлен."),
    "INVOICE_CANCELLED": ("cancelled", "Счёт отменён."),
    "PAYMENT_REFERENCE_CONFLICT": (
        "reference_conflict",
        "Платёж с таким номером операции уже записан с другой суммой или датой.",
    ),
}
# Отказы проверки ERP по одному полю тела BFF (поле ERP `paid_at` в теле BFF — `date`).
_FIELD_OF = {
    "PAYMENT_DATE_IN_FUTURE": "date",
    "PAYMENT_AMOUNT_MUST_BE_POSITIVE": "amount",
}
_FIELD_RENAMES = {"paid_at": "date", "confirmation_id": "proof_id"}
_NOT_FOUND = {
    "CONFIRMATION_NOT_FOUND": "Платёжка не найдена.",
    "NOT_FOUND": "Счёт не найден.",
}


def _code(response: httpx.Response) -> str | None:
    try:
        body = response.json()
    except ValueError:
        return None
    detail = body.get("detail") if isinstance(body, dict) else None
    return detail if isinstance(detail, str) else None


def payments_error(response: httpx.Response) -> PlatformError:
    """Ответ ERP 4xx -> `Error`: конфликт состояния счёта — 409 с причиной, поле суммы или даты —
    422, остальное — общий перевод.
    """
    status = response.status_code
    code = _code(response)
    details: dict[str, Any] = {"backend_status": status}
    if code:
        details["backend_code"] = code
    if status == 409 and code in _CONFLICTS:
        reason, message = _CONFLICTS[code]
        details["reason"] = reason
        if code == "PAYMENT_EXCEEDS_BALANCE_DUE":
            details["fields"] = ["amount"]
        return PlatformError("CONFLICT", message, status_code=409, source="erp", details=details)
    if status == 404 and code in _NOT_FOUND:
        return PlatformError(
            "NOT_FOUND", _NOT_FOUND[code], status_code=404, source="erp", details=details
        )
    if status == 400 and code in _FIELD_OF:
        details["reason"] = code.lower()
        details["fields"] = [_FIELD_OF[code]]
        return PlatformError(
            "VALIDATION_FAILED",
            "Проверьте заполнение полей.",
            status_code=422,
            source="erp",
            details=details,
        )
    error = erp_error(response)
    fields = (error.body.details or {}).get("fields")
    if isinstance(fields, list):
        renamed = [_FIELD_RENAMES.get(str(f), str(f)) for f in fields]
        error.body.details = {**(error.body.details or {}), "fields": renamed}
    if status == 403:
        return from_backend("erp", response)
    return error


# --- ERP: счета, платёжки, оплаты
# ------------------------------------------------------------------


def _dec(value: Any) -> Decimal:
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"), ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        return Decimal("0.00")


def _s(value: Any) -> str:
    return f"{_dec(value):.2f}"


def _date(value: Any) -> date | None:
    if isinstance(value, str) and len(value) >= 10:
        with contextlib.suppress(ValueError):
            return date.fromisoformat(value[:10])
    return None


def _dt(value: Any) -> datetime | None:
    if isinstance(value, str):
        with contextlib.suppress(ValueError):
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
    return None


def project_number(deal_id: int, year: int) -> str:
    """ПР-ГГГГ-NNN до ERP-09 (`Deal.number`): счёт бывает только у проекта, то есть после принятого
    КП.
    """
    return f"ПР-{year:04d}-{deal_id:03d}"


class Receivable(BaseModel):
    """Строка ERP `ReceivableRow`/`ReceivableCard` в той части, что нужна BFF; лишнее
    отбрасывается.
    """

    id: int
    number: str
    deal_id: int
    deal_year: int
    client_name: str
    currency: str | None
    total_incl_vat: str
    amount_paid: str
    balance_due: str
    issued_at: str | None
    due_date: str | None
    display_status: str
    days_overdue: int | None
    has_pending_proof: bool
    proof_received_at: str | None


def _money(amount: Any, currency: str | None) -> PaymentMoney:
    return PaymentMoney(amount=_s(amount), currency=currency or _DEFAULT_CURRENCY)


def row_of(raw: dict[str, Any]) -> PaymentRow:
    item = Receivable.model_validate(raw)
    return PaymentRow(
        id=item.id,
        number=item.number,
        project_number=project_number(item.deal_id, item.deal_year),
        deal_id=item.deal_id,
        client_name=item.client_name,
        amount=_money(item.total_incl_vat, item.currency),
        paid=_money(item.amount_paid, item.currency),
        balance=_money(item.balance_due, item.currency),
        issued_at=_date(item.issued_at),
        due_date=_date(item.due_date),
        status=cast(Any, item.display_status),
        days_overdue=item.days_overdue,
        has_pending_proof=item.has_pending_proof,
        proof_received_at=_dt(item.proof_received_at),
    )


def card_of(raw: dict[str, Any]) -> PaymentCard:
    try:
        return _card(raw)
    except (ValidationError, KeyError, TypeError, ValueError) as exc:
        raise backend_unavailable("erp", "bad_response") from exc


def _card(raw: dict[str, Any]) -> PaymentCard:
    base = row_of(raw)
    return PaymentCard(
        **base.model_dump(),
        subtotal=_s(raw.get("subtotal_excl_vat")),
        vat=_s(raw.get("vat_amount")),
        notes=str(raw.get("notes") or ""),
        has_pdf=bool(raw.get("has_pdf")),
        items=[
            PaymentItem(
                description=str(i.get("description") or ""),
                quantity=int(i.get("quantity") or 0),
                unit_price=_s(i.get("unit_price_excl_vat")),
                total=_s(i.get("line_total_excl_vat")),
            )
            for i in raw.get("items") or []
            if isinstance(i, dict)
        ],
        payments=[
            PaymentRecord(
                id=int(p["id"]),
                amount=_s(p.get("amount")),
                paid_at=_date(p.get("paid_at")) or date.min,
                method=str(p.get("method") or ""),
                reference=str(p.get("reference") or ""),
                receipt_number=str(p.get("receipt_number") or ""),
                has_proof=bool(p.get("has_proof")),
                recorded_by=p.get("recorded_by"),
                created_at=_dt(p.get("created_at")) or datetime.min,
            )
            for p in raw.get("payments") or []
            if isinstance(p, dict)
        ],
        proofs=[
            PaymentProof(
                id=int(c["id"]),
                source=cast(Any, c.get("source")),
                status=cast(Any, c.get("status")),
                original_name=str(c.get("original_name") or ""),
                claimed_amount=_s(c["claimed_amount"]) if c.get("claimed_amount") else None,
                claimed_date=_date(c.get("claimed_date")),
                note=str(c.get("note") or ""),
                received_at=_dt(c.get("received_at")) or datetime.min,
                recorded_by=c.get("recorded_by"),
                payment_id=c.get("payment_id"),
            )
            for c in raw.get("confirmations") or []
            if isinstance(c, dict)
        ],
        history=[
            PaymentHistoryEntry(
                at=_dt(h.get("at")) or datetime.min,
                code=str(h.get("code") or ""),
                text=str(h.get("text") or ""),
                by=h.get("by"),
            )
            for h in raw.get("history") or []
            if isinstance(h, dict)
        ],
        payment_doc_requested_at=_dt(raw.get("payment_doc_requested_at")),
        can_confirm=bool(raw.get("can_confirm")),
        can_attach_proof=bool(raw.get("can_attach_proof")),
        can_request_proof=bool(raw.get("can_request_proof")),
        replayed=bool(raw.get("replayed")),
    )


class Receivables:
    """Вызовы ERP «Счета и оплаты» от имени сотрудника."""

    def __init__(self, authed: Authed) -> None:
        self._authed = authed

    async def _json(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        content: bytes | None = None,
        content_type: str | None = None,
        headers: dict[str, str] | None = None,
        expected: int = 200,
    ) -> dict[str, Any]:
        response = await self._authed.call(
            "erp",
            method,
            f"{ERP_API}{path}",
            params=params,
            json=json,
            content=content,
            content_type=content_type,
            headers=headers,
        )
        if response.status_code != expected:
            raise payments_error(response)
        try:
            body = response.json()
        except ValueError as exc:
            raise backend_unavailable("erp", "bad_response") from exc
        if not isinstance(body, dict):
            raise backend_unavailable("erp", "bad_response")
        return body

    async def board(self, params: dict[str, Any]) -> dict[str, Any]:
        return await self._json("GET", "", params=params)

    async def card(self, invoice_id: int) -> dict[str, Any]:
        return await self._json("GET", f"{invoice_id}/")

    async def confirm(
        self, invoice_id: int, body: dict[str, Any], idempotency_key: str | None
    ) -> dict[str, Any]:
        headers = {"Idempotency-Key": idempotency_key} if idempotency_key else None
        return await self._json(
            "POST", f"{invoice_id}/confirm-payment/", json=body, headers=headers
        )

    async def attach_proof(
        self, invoice_id: int, content: bytes, content_type: str
    ) -> dict[str, Any]:
        return await self._json(
            "POST",
            f"{invoice_id}/confirmations/",
            content=content,
            content_type=content_type,
            expected=201,
        )

    async def request_doc(self, invoice_id: int) -> dict[str, Any]:
        return await self._json("POST", f"{invoice_id}/request-payment-doc/")

    async def proof_file(self, invoice_id: int, proof_id: int) -> httpx.Response:
        return await self._authed.call(
            "erp", "GET", f"{ERP_API}{invoice_id}/confirmations/{proof_id}/file/", stream=True
        )


def parse_board(
    raw: dict[str, Any], tab: InvoiceTab
) -> tuple[list[PaymentRow], int, PaymentCounts]:
    try:
        items = [row_of(r) for r in raw.get("results") or [] if isinstance(r, dict)]
        counts = PaymentCounts.model_validate(raw.get("counts") or {})
    except (ValidationError, KeyError, TypeError, ValueError) as exc:
        raise backend_unavailable("erp", "bad_response") from exc
    del tab
    return items, int(raw.get("count") or 0), counts


# --- EDS: служебки к оплате
# ---------------------------------------------------------------------------


def _memo_money(value: Any) -> PaymentMoney | None:
    if not isinstance(value, dict) or not value.get("amount") or not value.get("currency"):
        return None
    return PaymentMoney(amount=_s(value["amount"]), currency=str(value["currency"]))


def _person(value: Any) -> EdsPerson | None:
    if isinstance(value, dict) and isinstance(value.get("crm_user_id"), int):
        return EdsPerson(
            crm_user_id=value["crm_user_id"], full_name=str(value.get("full_name") or "")
        )
    return None


def memo_status(raw_status: Any) -> Literal["to_pay", "paid", "other"]:
    return (
        "to_pay" if raw_status == "to_accountant" else "paid" if raw_status == "paid" else "other"
    )


def memo_row(raw: dict[str, Any]) -> PaymentMemoRow:
    author = _person(raw.get("author")) or EdsPerson(crm_user_id=0, full_name="")
    count = int(raw.get("files_count") or 0)
    status = memo_status(raw.get("status"))
    return PaymentMemoRow(
        id=str(raw["id"]),
        number=raw.get("number"),
        subject=str(raw.get("subject") or ""),
        author=author,
        amount=_memo_money(raw.get("amount")),
        due_date=_date(raw.get("due_date")),
        files_count=count,
        invoice_attached=count > 0,
        status="paid" if status == "paid" else "to_pay",
        paid_on=_date(raw.get("paid_on")),
        created_at=_dt(raw.get("created_at")) or datetime.min,
    )


def memo_page(raw: Any) -> PaymentMemoPage:
    if not isinstance(raw, dict) or not isinstance(raw.get("items"), list):
        raise backend_unavailable("eds", "bad_response")
    try:
        return PaymentMemoPage(
            items=[memo_row(i) for i in raw["items"] if isinstance(i, dict)],
            next_cursor=raw.get("next_cursor"),
        )
    except (ValidationError, KeyError, TypeError) as exc:
        raise backend_unavailable("eds", "bad_response") from exc


def memo_card(raw: Any, approval: Any | None) -> PaymentMemoCard:
    if not isinstance(raw, dict) or raw.get("kind") != "memo":
        raise PlatformError(
            "NOT_FOUND", "Служебная записка не найдена.", status_code=404, source="eds"
        )
    try:
        payment = raw.get("payment")
        paid_by = _person(payment.get("paid_by")) if isinstance(payment, dict) else None
        money = _memo_money(payment.get("amount")) if isinstance(payment, dict) else None
        status = memo_status(raw.get("status"))
        decisions = approval.get("allowed_decisions") if isinstance(approval, dict) else []
        can_decide = bool(isinstance(approval, dict) and approval.get("can_decide"))
        accountant = _accountant_step(approval)
        return PaymentMemoCard(
            id=str(raw["id"]),
            approval_id=raw.get("approval_id"),
            number=raw.get("number"),
            subject=str(raw.get("subject") or ""),
            text=str(raw.get("text") or ""),
            author=_person(raw.get("author")) or EdsPerson(crm_user_id=0, full_name=""),
            amount=_memo_money(raw.get("amount")),
            due_date=_date(raw.get("due_date")),
            deal=EdsDealRef(erp_deal_id=raw["erp_deal_id"], number=raw.get("deal_number"))
            if isinstance(raw.get("erp_deal_id"), int)
            else None,
            files=[
                EdsFile(
                    id=str(f["id"]),
                    name=str(f.get("name") or ""),
                    content_type=str(f.get("content_type") or "application/octet-stream"),
                    size=int(f.get("size") or 0),
                )
                for f in raw.get("files") or []
                if isinstance(f, dict)
            ],
            document_status=str(raw.get("status") or ""),
            status=status,
            can_pay=status == "to_pay" and accountant and can_decide,
            can_return=status == "to_pay"
            and accountant
            and can_decide
            and isinstance(decisions, list)
            and "return" in decisions,
            payment=PaymentMemoPayment(
                paid_on=_date(payment.get("paid_on")) or date.min,
                amount=money or PaymentMoney(amount="0.00", currency=_DEFAULT_CURRENCY),
                receipt_file_id=payment.get("receipt_file_id"),
                note=payment.get("note"),
                paid_by=paid_by or EdsPerson(crm_user_id=0, full_name=""),
                recorded_at=_dt(payment.get("recorded_at")) or datetime.min,
            )
            if isinstance(payment, dict)
            else None,
            journal=[
                PaymentMemoJournal(
                    at=_dt(j.get("at")) or datetime.min,
                    action=str(j.get("action") or ""),
                    by=_person(j.get("by")),
                    comment=j.get("comment"),
                )
                for j in raw.get("journal") or []
                if isinstance(j, dict)
            ],
            created_at=_dt(raw.get("created_at")) or datetime.min,
        )
    except (ValidationError, KeyError, TypeError, ValueError) as exc:
        raise backend_unavailable("eds", "bad_response") from exc


def _accountant_step(approval: Any) -> bool:
    if not isinstance(approval, dict):
        return False
    return any(
        isinstance(s, dict)
        and s.get("status") == "current"
        and isinstance(s.get("assignee"), dict)
        and s["assignee"].get("permission") == "payments.confirm"
        for s in approval.get("steps") or []
    )


async def load_memo(proxy: EdsProxy, document_id: str) -> PaymentMemoCard:
    """Служебка и её маршрут (шаг, право решить) -> карточка «к оплате»."""
    doc = await proxy.request("GET", f"{EDS_API}/documents/{document_id}")
    approval = None
    approval_id = doc.get("approval_id") if isinstance(doc, dict) else None
    if isinstance(approval_id, str):
        approval = await proxy.request("GET", f"{EDS_API}/approvals/{approval_id}")
    return memo_card(doc, approval)


async def memos_to_pay_count(proxy: EdsProxy) -> int | None:
    """Сколько служебок ждут оплаты (до 100); EDS не ответил — `None`, вкладка «Служебки к оплате»
    без числа.
    """
    try:
        page = await proxy.request(
            "GET",
            f"{EDS_API}/documents",
            params={"kind": "memo", "status": "to_accountant", "limit": MEMOS_COUNT_LIMIT},
        )
    except PlatformError:
        return None
    items = page.get("items") if isinstance(page, dict) else None
    return len(items) if isinstance(items, list) else None


async def build_board(
    authed: Authed, *, tab: InvoiceTab, q: str | None, limit: int, offset: int
) -> PaymentBoard:
    params: dict[str, Any] = {"tab": tab, "limit": limit, "offset": offset}
    if q:
        params["q"] = q
    erp_raw, memos = await asyncio.gather(
        Receivables(authed).board(params), memos_to_pay_count(EdsProxy(authed.call))
    )
    items, count, counts = parse_board(erp_raw, tab)
    return PaymentBoard(
        tab=tab,
        count=count,
        counts=counts,
        memos_to_pay=memos,
        items=items,
        sources=PaymentSources(erp="ok", eds="ok" if memos is not None else "unavailable"),
    )
