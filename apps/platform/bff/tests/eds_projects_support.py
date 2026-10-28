"""ERP для тестов «Проекты» (D2-5): проекты, документы и действия — всё на respx,
ответы в форме `erp-internal.yaml`.

`ProjectsFake` отвечает на `GET /crm/projects/` и `/crm/projects/{id}/`, действия по
договору и акту, выпуск акта и файлы. Журнал `calls` показывает, что и с каким токеном ушло
в ERP; `answer()` подменяет ответ на конкретный вызов. Данные выдуманы.
"""

import json
import re
from collections.abc import Callable
from typing import Any

import httpx

from tests.backends import Backends
from tests.consts import ERP_URL

Answer = Callable[[httpx.Request], httpx.Response]

DEAL = 104
CONTRACT_ID = 311
ACT_ID = 520
INVOICE_ID = 4410
CREATED = "2026-10-20T09:20:00+05:00"
PDF = b"%PDF-1.4 demo"


def money(amount: str = "125000000.00") -> dict[str, str]:
    return {"amount": amount, "currency": "UZS"}


def history(code: str, document: str, number: str, reason: str = "") -> dict[str, Any]:
    return {
        "at": "2026-10-27T10:00:00+05:00",
        "code": code,
        "text": code,
        "actor_name": "Бухгалтер Демо",
        "document": document,
        "number": number,
        "reason": reason,
    }


def contract_card(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": CONTRACT_ID,
        "number": "ДОГ-2026/104",
        "status": "project",
        "sent_to_client": True,
        "total": money(),
        "created_at": "2026-10-21T10:00:00+05:00",
        "client_agreed_at": None,
        "signed_at": None,
        "has_pdf": True,
        "has_scan": False,
        "actions": ["client_agreed", "reject"],
        "history": [],
    }
    return {**base, **over}


def act_card(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": ACT_ID,
        "number": "АКТ-2026/058",
        "status": "issued",
        "total": money(),
        "issued_at": "2026-10-26",
        "signed_at": None,
        "rejection_reason": "",
        "has_pdf": True,
        "has_scan": False,
        "actions": ["attach_scan", "return"],
        "history": [],
    }
    return {**base, **over}


def invoice_card(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": INVOICE_ID,
        "number": "СЧ-2026/142",
        "status": "issued",
        "total": money(),
        "paid": money("0.00"),
        "balance_due": money(),
        "issued_at": "2026-10-24",
        "due_date": "2026-11-07",
        "has_pdf": True,
    }
    return {**base, **over}


def row(deal_id: int = DEAL, **over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "deal_id": deal_id,
        "title": "Стрелочные приводы",
        "company_id": 7,
        "company_name": "ООО «Демо-Рейл»",
        "created_at": CREATED,
        "step": "CONTRACT",
        "client_status": "contract_review",
        "total": money(),
        "manager": {"id": 2, "name": "Менеджер Демо"},
        "responsible": {"id": 2, "name": "Менеджер Демо"},
        "due_date": None,
        "documents": {
            "quote": {"id": 1203, "number": "КП-2026/115", "status": "accepted", "version": 2},
            "contract": {
                "id": CONTRACT_ID,
                "number": "ДОГ-2026/104",
                "status": "project",
                "sent_to_client": True,
            },
            "invoice": None,
            "act": None,
        },
        "problems": [],
    }
    return {**base, **over}


def card(deal_id: int = DEAL, **over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        **row(deal_id),
        "quote": {
            "id": 1203,
            "number": "КП-2026/115",
            "status": "accepted",
            "version": 2,
            "outgoing_number": "ИСХ-082/26",
            "valid_until": "2026-11-27",
        },
        "contract": contract_card(),
        "can_create_contract": False,
        "invoices": [],
        "act": None,
        "act_blocker": "no_invoice",
        "fulfillment": None,
        "delivery_lines": [],
        "journal": [],
    }
    return {**base, **over}


class ProjectsFake:
    """Проекты ERP; состояние (`rows`, `cards`) тест меняет на лету."""

    def __init__(self, be: Backends) -> None:
        self.be = be
        self.rows: list[dict[str, Any]] = [row()]
        self.cards: dict[int, dict[str, Any]] = {DEAL: card()}
        self.calls: list[httpx.Request] = []
        self.overrides: list[tuple[str, re.Pattern[str], Answer]] = []
        self.after: Callable[[httpx.Request], None] | None = None
        self.files: dict[str, bytes] = {}
        base = re.escape(f"{ERP_URL}/api/v1/crm/")
        be.router.route(url__regex=rf"^{base}(projects|contracts|acts|invoices)/.*").mock(
            side_effect=self._handle
        )

    def answer(self, method: str, path_regex: str, response: Answer | httpx.Response) -> None:
        """Подменить ответ ERP на вызов: `path_regex` — путь после `/api/v1/crm/`."""
        handler: Answer = response if callable(response) else (lambda _r: response)
        self.overrides.insert(0, (method, re.compile(path_regex), handler))

    def calls_to(self, method: str, path_regex: str) -> list[httpx.Request]:
        pattern = re.compile(path_regex)
        return [
            c
            for c in self.calls
            if c.method == method and pattern.fullmatch(c.url.path.removeprefix("/api/v1/crm/"))
        ]

    def posts(self) -> list[httpx.Request]:
        return [c for c in self.calls if c.method == "POST"]

    def body(self, method: str, path_regex: str) -> Any:
        [call] = self.calls_to(method, path_regex)
        return json.loads(call.content) if call.content else None

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        tail = request.url.path.removeprefix("/api/v1/crm/")
        for method, pattern, handler in self.overrides:
            if request.method == method and pattern.fullmatch(tail):
                return handler(request)
        if not request.headers.get("authorization", "").startswith("Bearer "):
            return httpx.Response(401, json={"detail": "x"})
        if request.method == "GET":
            return self._get(request, tail)
        response = self._post(tail)
        if response.status_code < 300 and self.after is not None:
            self.after(request)
        return response

    def _get(self, request: httpx.Request, tail: str) -> httpx.Response:
        if tail == "projects/":
            params = request.url.params
            rows = list(self.rows)
            if "deal_id" in params:
                rows = [r for r in rows if r["deal_id"] == int(params["deal_id"])]
            offset, limit = int(params.get("offset", 0)), int(params.get("limit", 25))
            return httpx.Response(
                200, json={"count": len(rows), "results": rows[offset : offset + limit]}
            )
        match = re.fullmatch(r"projects/(\d+)/", tail)
        if match:
            found = self.cards.get(int(match[1]))
            if found is None:
                return httpx.Response(404, json={"detail": "NOT_FOUND"})
            return httpx.Response(200, json=found)
        match = re.fullmatch(
            r"(contracts|acts|invoices)/(\d+)/(download-pdf|download-signed)/", tail
        )
        if match:
            return httpx.Response(
                200,
                content=self.files.get(tail, PDF),
                headers={"Content-Disposition": 'attachment; filename="doc.pdf"'},
            )
        return httpx.Response(404, json={"detail": "NOT_FOUND"})

    def _post(self, tail: str) -> httpx.Response:
        if tail == "contracts/generate-from-quote/":
            return httpx.Response(201, json={"id": CONTRACT_ID})
        if re.fullmatch(r"invoices/\d+/generate-act/", tail):
            return httpx.Response(201, json={"id": ACT_ID})
        if re.fullmatch(r"(contracts|acts)/\d+/[a-z-]+/", tail):
            return httpx.Response(200, json={"id": 1})
        return httpx.Response(404, json={"detail": "NOT_FOUND"})


def erp_error(status: int, code: str) -> httpx.Response:
    return httpx.Response(status, json={"detail": code})
