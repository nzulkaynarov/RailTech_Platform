"""ERP и EDS для тестов «Счета и оплаты» (D2-4): всё на respx.

ERP — по `finance/views_receivables.py` (ответы доски и карточки в формате `erp-internal.yaml`):
держит счета, платёжки и платежи в памяти и повторяет правила ERP, на которые опирается BFF
(остаток, «сумма больше остатка», идемпотентность по `Idempotency-Key`, повтор по оплаченному
счёту). Настоящую логику проверяют тесты ERP (`finance/tests/test_receivables.py`); здесь
проверяется оркестровка BFF. EDS — служебки к оплате и «Оплачено» (`eds.yaml` 0.5.0).
"""

import json
import re
from decimal import Decimal
from typing import Any

import httpx

from tests.backends import Backends
from tests.consts import ERP_URL
from tests.eds_approvals_support import ApprovalsFake, memo_route, step
from tests.eds_letters_support import person

RECEIVABLES = f"{ERP_URL}/api/v1/finance/receivables/"
TODAY = "2026-10-28"
PAY_DOC = "61000000-0000-4000-8000-000000000031"
PAY_DOC_NUMBER = "СЗ-2026/031"
PAY_ROUTE = "51000000-0000-4000-8000-000000000031"
INVOICE_FILE = "71000000-0000-4000-8000-000000000031"
RECEIPT_FILE = "71000000-0000-4000-8000-000000000032"


def dec(value: Any) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"))


def invoice(inv_id: int = 142, **over: Any) -> dict[str, Any]:
    """Счёт ERP в состоянии «Выставлен», 112 000 000 UZS, срок 10 дней вперёд."""
    base: dict[str, Any] = {
        "id": inv_id,
        "number": f"СЧ-2026/{inv_id}",
        "deal_id": 104,
        "deal_title": "Стрелочные приводы",
        "deal_year": 2026,
        "client_id": 7,
        "client_name": "ООО «Демо-Рейл»",
        "currency": "UZS",
        "total_incl_vat": "112000000.00",
        "subtotal_excl_vat": "100000000.00",
        "vat_amount": "12000000.00",
        "amount_paid": "0.00",
        "issued_at": "2026-10-20",
        "due_date": "2026-11-07",
        "status": "ISSUED",
        "notes": "",
        "has_pdf": True,
        "items": [
            {
                "id": 1,
                "description": "Привод стрелочный СП-6",
                "quantity": 12,
                "unit_price_excl_vat": "8333333.33",
                "line_total_excl_vat": "100000000.00",
            }
        ],
        "payments": [],
        "confirmations": [],
        "history": [],
    }
    return {**base, **over}


def proof(proof_id: int = 5, **over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": proof_id,
        "source": "CABINET",
        "status": "PENDING",
        "original_name": "платёжка.pdf",
        "claimed_amount": "112000000.00",
        "claimed_date": "2026-10-27",
        "note": "",
        "received_at": "2026-10-27T15:00:00Z",
        "recorded_by": None,
        "payment_id": None,
    }
    return {**base, **over}


def display_status(inv: dict[str, Any]) -> str:
    code = inv["status"]
    balance = dec(inv["total_incl_vat"]) - dec(inv["amount_paid"])
    pending = any(c["status"] == "PENDING" for c in inv["confirmations"])
    if code == "CANCELLED":
        return "cancelled"
    if code == "PAID":
        return "paid"
    if code == "DRAFT":
        return "draft"
    if pending:
        return "proof_received"
    if inv["due_date"] and inv["due_date"] < TODAY and balance > 0:
        return "overdue"
    return "partially_paid" if code == "PARTIAL" else "issued"


def tab_of(inv: dict[str, Any]) -> str:
    shown = display_status(inv)
    return {"draft": "to_issue", "proof_received": "proofs", "overdue": "overdue"}.get(
        shown, "awaiting" if shown in ("issued", "partially_paid") else "all"
    )


def erp_row(inv: dict[str, Any]) -> dict[str, Any]:
    shown = display_status(inv)
    pending = [c for c in inv["confirmations"] if c["status"] == "PENDING"]
    days = None
    if shown == "overdue":
        days = (
            int(TODAY[-2:])
            - int(inv["due_date"][-2:])
            + 30 * (int(TODAY[5:7]) - int(inv["due_date"][5:7]))
        )
    return {
        "id": inv["id"],
        "number": inv["number"],
        "deal_id": inv["deal_id"],
        "deal_title": inv["deal_title"],
        "deal_year": inv["deal_year"],
        "client_id": inv["client_id"],
        "client_name": inv["client_name"],
        "currency": inv["currency"],
        "total_incl_vat": inv["total_incl_vat"],
        "amount_paid": inv["amount_paid"],
        "balance_due": f"{dec(inv['total_incl_vat']) - dec(inv['amount_paid']):.2f}",
        "issued_at": inv["issued_at"],
        "due_date": inv["due_date"],
        "status": inv["status"],
        "display_status": shown,
        "is_overdue": shown == "overdue",
        "days_overdue": days,
        "has_pending_proof": bool(pending),
        "proof_received_at": pending[0]["received_at"] if pending else None,
    }


def pay_doc(**over: Any) -> dict[str, Any]:
    """Служебка EDS, согласованная директором и переданная бухгалтеру (`to_accountant`), счёт
    поставщика приложен.
    """
    base: dict[str, Any] = {
        "id": PAY_DOC,
        "kind": "memo",
        "number": PAY_DOC_NUMBER,
        "status": "to_accountant",
        "version": 1,
        "subject": "Оплата аренды склада за ноябрь",
        "text": "Прошу оплатить аренду склада. Счёт приложен.",
        "author": person(2, "Менеджер Демо"),
        "addressee": None,
        "amount": {"amount": "8500000.00", "currency": "UZS"},
        "due_date": "2026-10-31",
        "files": [
            {
                "id": INVOICE_FILE,
                "name": "счёт-аренда.pdf",
                "content_type": "application/pdf",
                "size": 40960,
            }
        ],
        "erp_deal_id": None,
        "deal_number": None,
        "approval_id": PAY_ROUTE,
        "payment": None,
        "journal": [
            {
                "at": "2026-10-27T10:00:00Z",
                "action": "document.submitted",
                "by": person(2, "Менеджер Демо"),
                "comment": None,
            }
        ],
        "decisions": [],
        "created_at": "2026-10-27T10:00:00Z",
        "updated_at": "2026-10-27T10:00:00Z",
    }
    return {**base, **over}


def pay_route(**over: Any) -> dict[str, Any]:
    accountant = step(
        2,
        "Бухгалтер",
        "current",
        assignee={"crm_user_id": None, "permission": "payments.confirm"},
    )
    base = memo_route(
        id=PAY_ROUTE,
        title=f"{PAY_DOC_NUMBER} · Оплата аренды склада за ноябрь",
        object={"kind": "memo", "document_id": PAY_DOC, "number": PAY_DOC_NUMBER},
        steps=[step(1, "Директор", "approved"), accountant],
        can_decide=True,
        allowed_decisions=["return", "reject"],
    )
    return {**base, **over}


def list_item(doc: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "id",
        "kind",
        "number",
        "status",
        "subject",
        "author",
        "amount",
        "due_date",
        "created_at",
    )
    return {
        **{k: doc[k] for k in keys},
        "files_count": len(doc["files"]),
        "paid_on": doc["payment"]["paid_on"] if doc["payment"] else None,
    }


def eds_error(code: str, message: str, **details: Any) -> dict[str, Any]:
    return {"code": code, "message": message, "source": "eds", "details": details}


class PaymentsFake(ApprovalsFake):
    """ERP со счетами и EDS со служебкой к оплате; журнал запросов к ERP."""

    def __init__(self, be: Backends) -> None:
        super().__init__(be)
        self.invoices: dict[int, dict[str, Any]] = {
            142: invoice(142),
            143: invoice(143, status="DRAFT", issued_at=None, due_date=None),
            144: invoice(144, due_date="2026-10-20", number="СЧ-2026/144"),
            145: invoice(145, confirmations=[proof(5)], number="СЧ-2026/145"),
            146: invoice(146, status="PAID", amount_paid="112000000.00", number="СЧ-2026/146"),
        }
        self.erp_status: int | Exception = 200
        self.reject_date = False
        self.erp_requests: list[httpx.Request] = []
        self.idempotent: dict[str, httpx.Response] = {}
        self.proof_bytes = b"%PDF-1.4 platezhka"
        self.next_payment = 900
        self.next_proof = 50
        self.documents[PAY_DOC] = pay_doc()
        self.routes[PAY_ROUTE] = pay_route()
        self.eds_list_status: int = 200
        self.paid: list[dict[str, Any]] = []
        be.router.route(url__regex=rf"^{re.escape(RECEIVABLES)}.*").mock(side_effect=self._erp_rec)

    # --- ERP --------------------------------------------------------------------------------
    def erp_made(self, method: str, tail: str = "") -> list[httpx.Request]:
        path = f"/api/v1/finance/receivables/{tail}"
        return [r for r in self.erp_requests if r.method == method and r.url.path == path]

    def _erp_rec(self, request: httpx.Request) -> httpx.Response:
        self.erp_requests.append(request)
        if isinstance(self.erp_status, Exception):
            raise self.erp_status
        if self.erp_status != 200:
            return httpx.Response(self.erp_status, json={"detail": "ROLE_NOT_PERMITTED"})
        tail = request.url.path.removeprefix("/api/v1/finance/receivables/")
        if tail == "" and request.method == "GET":
            return self._board(request)
        match = re.fullmatch(
            r"(\d+)/(?:(confirm-payment|confirmations|request-payment-doc)/)?", tail
        )
        if match:
            inv = self.invoices.get(int(match[1]))
            if inv is None:
                return httpx.Response(404, json={"detail": "NOT_FOUND"})
            if match[2] is None:
                return httpx.Response(200, json=self._card(inv))
            if match[2] == "confirm-payment":
                return self._confirm(request, inv)
            if match[2] == "confirmations":
                return self._attach(request, inv)
            return self._request_doc(inv)
        match = re.fullmatch(r"(\d+)/confirmations/(\d+)/file/", tail)
        if match:
            inv = self.invoices.get(int(match[1]))
            found = [c for c in (inv or {}).get("confirmations", []) if c["id"] == int(match[2])]
            if not found:
                return httpx.Response(404, json={"detail": "NOT_FOUND"})
            return httpx.Response(
                200,
                content=self.proof_bytes,
                headers={
                    "content-type": "application/pdf",
                    "content-disposition": "attachment; filename=pp.pdf",
                },
            )
        return httpx.Response(404, json={"detail": "NOT_FOUND"})

    def _board(self, request: httpx.Request) -> httpx.Response:
        tab = request.url.params.get("tab", "awaiting")
        needle = request.url.params.get("q", "").casefold()
        limit = int(request.url.params.get("limit", 50))
        offset = int(request.url.params.get("offset", 0))
        rows = [
            erp_row(i)
            for i in self.invoices.values()
            if (tab == "all" or tab_of(i) == tab)
            and (
                not needle
                or needle in i["number"].casefold()
                or needle in i["client_name"].casefold()
            )
        ]
        counts = {
            name: sum(1 for i in self.invoices.values() if tab_of(i) == name)
            for name in ("to_issue", "awaiting", "proofs", "overdue")
        }
        return httpx.Response(
            200,
            json={
                "tab": tab,
                "count": len(rows),
                "counts": counts,
                "results": rows[offset : offset + limit],
            },
        )

    def _card(self, inv: dict[str, Any], *, replayed: bool = False) -> dict[str, Any]:
        open_invoice = inv["status"] in ("ISSUED", "PARTIAL", "OVERDUE")
        return {
            **erp_row(inv),
            "subtotal_excl_vat": inv["subtotal_excl_vat"],
            "vat_amount": inv["vat_amount"],
            "notes": inv["notes"],
            "has_pdf": inv["has_pdf"],
            "items": inv["items"],
            "payments": inv["payments"],
            "confirmations": inv["confirmations"],
            "history": inv["history"],
            "payment_doc_requested_at": inv.get("requested_at"),
            "can_confirm": open_invoice,
            "can_attach_proof": open_invoice,
            "can_request_proof": open_invoice,
            "replayed": replayed,
        }

    def _confirm(self, request: httpx.Request, inv: dict[str, Any]) -> httpx.Response:
        key = request.headers.get("idempotency-key")
        if key and key in self.idempotent:
            return self.idempotent[key]
        body = json.loads(request.content)
        amount = dec(body["amount"])
        balance = dec(inv["total_incl_vat"]) - dec(inv["amount_paid"])
        confirmation_id = body.get("confirmation_id")
        confirmation = next((c for c in inv["confirmations"] if c["id"] == confirmation_id), None)
        if confirmation_id is not None and confirmation is None:
            return httpx.Response(404, json={"detail": "CONFIRMATION_NOT_FOUND"})
        if confirmation is not None and confirmation["status"] == "CONFIRMED":
            return httpx.Response(200, json=self._card(inv, replayed=True))
        last = inv["payments"][-1] if inv["payments"] else None
        if (
            inv["status"] == "PAID"
            and last
            and dec(last["amount"]) == amount
            and last["paid_at"] == body["paid_at"]
        ):
            return httpx.Response(200, json=self._card(inv, replayed=True))
        if inv["status"] == "PAID":
            return httpx.Response(409, json={"detail": "INVOICE_ALREADY_PAID"})
        if inv["status"] == "DRAFT":
            return httpx.Response(409, json={"detail": "INVOICE_NOT_ISSUED"})
        if amount <= 0:
            return httpx.Response(400, json={"detail": "PAYMENT_AMOUNT_MUST_BE_POSITIVE"})
        if body["paid_at"] > TODAY or self.reject_date:
            return httpx.Response(400, json={"detail": "PAYMENT_DATE_IN_FUTURE"})
        if amount > balance:
            return httpx.Response(409, json={"detail": "PAYMENT_EXCEEDS_BALANCE_DUE"})
        self.next_payment += 1
        inv["payments"].append(
            {
                "id": self.next_payment,
                "amount": f"{amount:.2f}",
                "paid_at": body["paid_at"],
                "method": "BANK_TRANSFER",
                "receipt_number": f"RCP-{self.next_payment}",
                "reference": body.get("reference") or "",
                "has_proof": confirmation is not None,
                "recorded_by": "Бахтиёр Бухгалтеров",
                "created_at": "2026-10-28T09:00:00Z",
            }
        )
        inv["amount_paid"] = f"{dec(inv['amount_paid']) + amount:.2f}"
        inv["status"] = (
            "PAID" if dec(inv["amount_paid"]) >= dec(inv["total_incl_vat"]) else "PARTIAL"
        )
        if confirmation is not None:
            confirmation["status"] = "CONFIRMED"
            confirmation["payment_id"] = self.next_payment
        inv["history"].insert(
            0,
            {
                "at": "2026-10-28T09:00:00Z",
                "code": "payment.recorded",
                "text": "Зафиксирован платёж",
                "by": "Бахтиёр Бухгалтеров",
            },
        )
        response = httpx.Response(200, json=self._card(inv))
        if key:
            self.idempotent[key] = response
        return response

    def _attach(self, request: httpx.Request, inv: dict[str, Any]) -> httpx.Response:
        if inv["status"] not in ("ISSUED", "PARTIAL", "OVERDUE"):
            return httpx.Response(409, json={"detail": "INVOICE_NOT_OPEN"})
        self.next_proof += 1
        inv["confirmations"].append(
            proof(self.next_proof, source="EMAIL", recorded_by="Бахтиёр Бухгалтеров")
        )
        return httpx.Response(201, json=self._card(inv))

    def _request_doc(self, inv: dict[str, Any]) -> httpx.Response:
        if inv["status"] not in ("ISSUED", "PARTIAL", "OVERDUE"):
            return httpx.Response(409, json={"detail": "INVOICE_NOT_OPEN"})
        inv["requested_at"] = "2026-10-28T09:10:00Z"
        inv["history"].insert(
            0,
            {
                "at": "2026-10-28T09:10:00Z",
                "code": "payment_doc.requested",
                "text": "Запрошена платёжка у клиента",
                "by": "Бахтиёр Бухгалтеров",
            },
        )
        return httpx.Response(200, json=self._card(inv))

    # --- EDS --------------------------------------------------------------------------------
    def _upload(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        return httpx.Response(
            201,
            json={
                "id": RECEIPT_FILE,
                "name": "платёжка.pdf",
                "content_type": "application/pdf",
                "size": 2048,
                "version": 1,
                "sha256": "b" * 64,
                "uploaded_at": "2026-10-28T09:00:00Z",
                "uploaded_by": person(6, "Бахтиёр Бухгалтеров"),
            },
        )

    def _handle(self, request: httpx.Request) -> httpx.Response:
        tail = request.url.path.removeprefix("/api/v1/")
        if request.method == "POST" and tail == "files":
            return self._upload(request)
        if request.method == "GET" and tail == "documents":
            self.calls.append(request)
            if self.eds_list_status != 200:
                return httpx.Response(self.eds_list_status, json=eds_error("INTERNAL_ERROR", "x"))
            wanted = request.url.params.get("status")
            items = [
                list_item(d)
                for d in self.documents.values()
                if d["kind"] == "memo" and (wanted is None or d["status"] == wanted)
            ]
            return httpx.Response(200, json={"items": items, "next_cursor": None})
        match = re.fullmatch(r"documents/([0-9a-f-]{36})/payment", tail)
        if request.method == "POST" and match:
            self.calls.append(request)
            if (request.method, tail) in self.overrides:
                return self.overrides[(request.method, tail)](request)
            return self._pay(match[1], json.loads(request.content))
        return super()._handle(request)

    def _pay(self, doc_id: str, body: dict[str, Any]) -> httpx.Response:
        doc = self.documents.get(doc_id)
        if doc is None:
            return httpx.Response(404, json=eds_error("NOT_FOUND", "Документ не найден."))
        if doc["payment"] is not None:
            same = (
                doc["payment"]["paid_on"] == body["paid_on"]
                and doc["payment"]["amount"] == body["amount"]
            )
            if same:
                return httpx.Response(200, json=doc)
            return httpx.Response(
                409, json=eds_error("CONFLICT", "Записка уже оплачена.", reason="already_paid")
            )
        if doc["status"] != "to_accountant":
            return httpx.Response(
                409,
                json=eds_error(
                    "CONFLICT", "Записка не передана бухгалтеру.", reason="invalid_state"
                ),
            )
        if dec(body["amount"]["amount"]) > dec(doc["amount"]["amount"]):
            return httpx.Response(
                422,
                json=eds_error(
                    "VALIDATION_FAILED",
                    "Сумма оплаты больше согласованной директором.",
                    fields=[
                        {"field": "amount", "message": "exceeds_approved", "type": "value_error"}
                    ],
                ),
            )
        self.paid.append(body)
        paid_by = person(6, "Бахтиёр Бухгалтеров")
        doc["status"] = "paid"
        doc["payment"] = {
            "paid_on": body["paid_on"],
            "amount": body["amount"],
            "receipt_file_id": body.get("receipt_file_id"),
            "note": body.get("note"),
            "paid_by": paid_by,
            "recorded_at": "2026-10-28T09:30:00Z",
        }
        doc["journal"].append(
            {
                "at": "2026-10-28T09:30:00Z",
                "action": "document.paid",
                "by": paid_by,
                "comment": f"{body['paid_on']}, {body['amount']['amount']}",
            }
        )
        self.routes[PAY_ROUTE] = pay_route(
            status="approved", can_decide=False, allowed_decisions=[]
        )
        return httpx.Response(200, json=doc)
