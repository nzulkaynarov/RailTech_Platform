"""EDS и ERP для тестов «КП на одобрение» и «На согласовании» (D1-4): всё на respx.

EDS — по `eds.yaml` (`Approval`, `ApprovalPage`, `Document`, `DecisionIn`): принимает только свой
токен доступа (обмен SSO-токена CRM `aud=eds`, как в `eds_letters_support`); ответы выдуманы. ERP
отдаёт КП (`/crm/quotes/{id}/`: состав, доступность каналов, итог отправки) и заявку, принимает
«Отправить по каналу» (`deliver`); CRM — «почта настроена»; решения ведёт `ApprovalsFake`.
"""

import json
import re
from typing import Any

import httpx

from tests.backends import Backends
from tests.consts import CRM_URL, ERP_URL
from tests.eds_letters_support import EdsFake, person

QUOTE_ROUTE = "40000000-0000-4000-8000-000000000115"
QUOTE_ROUTE_OLD = "40000000-0000-4000-8000-000000000114"
MEMO_ROUTE = "50000000-0000-4000-8000-000000000014"
MEMO_DOC = "60000000-0000-4000-8000-000000000014"
MEMO_FILE = "70000000-0000-4000-8000-000000000001"
QUOTE_NUMBER = "КП-2026/115"
MEMO_NUMBER = "СЗ-2026/014"


def step(index: int, label: str, status: str, **over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "index": index,
        "label": label,
        "assignee": {"crm_user_id": None, "permission": "approvals.decide"},
        "status": status,
        "decided_by": None,
        "decided_at": None,
        "comment": None,
    }
    return {**base, **over}


def check(code: str, ok: bool, *, blocking: bool = True, **over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "code": code,
        "label": code,
        "ok": ok,
        "blocking": blocking,
        "by": None,
        "at": None,
        "value": None,
    }
    return {**base, **over}


def checklist_green() -> list[dict[str, Any]]:
    return [
        check(
            "visa_goods",
            True,
            by=person(3, "Снабженец Демо"),
            at="2026-10-28T07:40:00Z",
        ),
        check(
            "visa_services",
            True,
            by=person(4, "Инженер Демо"),
            at="2026-10-28T08:10:00Z",
        ),
        check("margin", True, value="17.6 % ≥ 15 %", at="2026-10-28T08:55:00Z"),
        check("due", True, blocking=False, value="2026-10-29"),
    ]


def snapshot(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "erp_quote_id": 1203,
        "number": QUOTE_NUMBER,
        "version": 2,
        "client_name": "ООО «Демо-Рейл»",
        "total": "125000000.00",
        "currency": "UZS",
        "cost": "103000000.00",
        "margin_amount": "22000000.00",
        "margin_pct": "17.6",
        "min_margin_pct": "15",
        "required_zones": ["goods", "services"],
        "visas": [
            {"zone": "goods", "by": person(3, "Снабженец Демо"), "at": "2026-10-28T07:40:00Z"},
            {"zone": "services", "by": person(4, "Инженер Демо"), "at": "2026-10-28T08:10:00Z"},
        ],
        "due": "2026-10-29",
        "ready_at": "2026-10-28T08:55:00Z",
        "valid_until": "2026-11-27",
    }
    return {**base, **over}


def quote_route(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": QUOTE_ROUTE,
        "template": "quote",
        "title": f"{QUOTE_NUMBER} v2 · ЗВ-2026-104",
        "object": {
            "kind": "quote",
            "erp_quote_id": 1203,
            "quote_number": QUOTE_NUMBER,
            "quote_version": 2,
            "erp_deal_id": 5,
            "deal_number": "ЗВ-2026-104",
        },
        "status": "open",
        "round": 2,
        "steps": [step(1, "Директор", "current")],
        "checklist": checklist_green(),
        "quote": snapshot(),
        "can_decide": True,
        "allowed_decisions": ["approve", "return", "reject"],
        "outgoing_number": None,
        "approved_late": False,
        "created_at": "2026-10-28T08:56:00Z",
        "closed_at": None,
    }
    return {**base, **over}


def memo_doc(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": MEMO_DOC,
        "kind": "memo",
        "number": MEMO_NUMBER,
        "status": "on_approval",
        "version": 1,
        "subject": "Оплата аренды склада за ноябрь",
        "text": "Прошу согласовать оплату аренды склада.\nСчёт приложен.",
        "author": person(2, "Менеджер Демо"),
        "addressee": None,
        "amount": {"amount": "8500000.00", "currency": "UZS"},
        "due_date": "2026-10-31",
        "files": [
            {
                "id": MEMO_FILE,
                "name": "счёт-аренда.pdf",
                "content_type": "application/pdf",
                "size": 40960,
            }
        ],
        "erp_deal_id": None,
        "deal_number": None,
        "approval_id": MEMO_ROUTE,
        "decisions": [],
        "created_at": "2026-10-27T10:00:00Z",
        "updated_at": "2026-10-27T10:00:00Z",
    }
    return {**base, **over}


def memo_route(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": MEMO_ROUTE,
        "template": "memo",
        "title": "Оплата аренды склада за ноябрь",
        "object": {"kind": "memo", "document_id": MEMO_DOC, "number": MEMO_NUMBER},
        "status": "open",
        "round": 1,
        "steps": [step(1, "Директор", "current"), step(2, "Бухгалтер", "pending")],
        "checklist": [],
        "quote": None,
        "can_decide": True,
        "allowed_decisions": ["approve", "return", "reject"],
        "outgoing_number": None,
        "approved_late": False,
        "created_at": "2026-10-27T10:01:00Z",
        "closed_at": None,
    }
    return {**base, **over}


def list_item(route: dict[str, Any]) -> dict[str, Any]:
    current = next((s for s in route["steps"] if s["status"] == "current"), None)
    keys = ("id", "template", "title", "object", "status", "created_at")
    return {**{k: route[k] for k in keys}, "round": route["round"], "current_step": current}


def erp_quote(**over: Any) -> dict[str, Any]:
    """Ответ ERP `GET /crm/quotes/{id}/` (подмножество `Quote`); поля экономики — как отдаёт ERP."""
    base: dict[str, Any] = {
        "id": 1203,
        "deal": 5,
        "quote_currency": "UZS",
        "vat_rate": "12.00",
        "subtotal_excl_vat": "111607142.86",
        "vat_amount": "13392857.14",
        "total_incl_vat": "125000000.00",
        "valid_until": "2026-11-27",
        "margin_percent": "17.60",
        "charges_total": "100.00",
        "economics": {"cost": "103000000.00"},
        "status_code": "PENDING_APPROVAL",
        "can_send": True,
        "send_report": {},
        "channel_availability": availability(),
        "client_comments": [
            {
                "id": 1,
                "author": "client",
                "author_name": "Алия Демо",
                "text": "Можно срок 30 дней?",
                "created_at": "2026-10-20T10:00:00+05:00",
            },
            {
                "id": 2,
                "author": "manager",
                "author_name": "",
                "text": "Уточним",
                "created_at": "bad",
            },
        ],
        "items": [
            {
                "display_type": "SECTION",
                "name_canonical": "Раздел 1",
                "quantity": 0,
                "final_price_excl_vat": "0.00",
            },
            {
                "display_type": "ITEM",
                "name_canonical": "Привод стрелочный СП-6",
                "product_name": "СП-6",
                "unit": "шт",
                "quantity": 12,
                "final_price_excl_vat": "8500000.00",
                "lead_time_days": 45,
                "landed_cost": "7000000.00",
                "margin_percent": "17.60",
            },
            {
                "display_type": "ITEM",
                "product_name": "Шефмонтаж",
                "product_uom": "усл",
                "quantity": 1,
                "final_price_excl_vat": "9607142.86",
                "lead_time_days": 10,
                "is_optional": True,
            },
        ],
    }
    return {**base, **over}


def erp_deal(**over: Any) -> dict[str, Any]:
    return {
        "id": 5,
        "title": "Стрелочные приводы",
        "company_name": "ООО «Демо-Рейл»",
        "client": 77,
        "client_name": "Алия Демо",
        "stage_code": "QUOTE_SENT",
        "execution_complete": False,
        "created_at": "2026-10-24T09:20:00Z",
        **over,
    }


def availability(
    *, telegram: str | None = None, cabinet: str | None = None, email: str | None = None
) -> dict[str, Any]:
    """ERP `channel_availability` КП (D17G-2): аргумент — код причины недоступного канала."""
    reasons = {"telegram": telegram, "cabinet": cabinet, "email": email}
    return {
        "contact_name": "Алия Демо",
        "channels": [
            {"channel": c, "available": r is None, "reason": r} for c, r in reasons.items()
        ],
    }


class ApprovalsFake(EdsFake):
    """EDS с маршрутами согласования и документами; ERP с КП и контактом; журнал решений."""

    def __init__(self, be: Backends) -> None:
        super().__init__(be)
        self.routes: dict[str, dict[str, Any]] = {
            QUOTE_ROUTE: quote_route(),
            MEMO_ROUTE: memo_route(),
        }
        self.documents: dict[str, dict[str, Any]] = {MEMO_DOC: memo_doc()}
        self.listing: dict[str, list[str]] = {"quote": [QUOTE_ROUTE], "memo": [MEMO_ROUTE]}
        self.registry = [
            {
                "kind": "quote",
                "id": QUOTE_ROUTE_OLD,
                "number": QUOTE_NUMBER,
                "status": "returned",
                "registered_at": "2026-10-27T08:00:00Z",
            },
            {
                "kind": "quote",
                "id": QUOTE_ROUTE,
                "number": QUOTE_NUMBER,
                "status": "open",
                "registered_at": "2026-10-28T08:56:00Z",
            },
            {
                "kind": "memo",
                "id": MEMO_DOC,
                "number": MEMO_NUMBER,
                "status": "on_approval",
                "registered_at": "2026-10-27T10:00:00Z",
            },
        ]
        self.erp_quote: dict[str, Any] | int | Exception | None = erp_quote()
        self.erp_paths: list[str] = []
        self.smtp_ready: dict[str, Any] | int = {"configured": True}
        # Ответ ERP на `deliver`: None — 200 (КП отправлено), иначе (статус, код ERP).
        self.deliver_error: tuple[int, str] | None = None
        self.delivered: list[dict[str, Any]] = []
        be.router.get(url__regex=rf"^{re.escape(ERP_URL)}/api/v1/crm/quotes/\d+/$").mock(
            side_effect=lambda r: self._erp(r, self.erp_quote)
        )
        be.router.post(url__regex=rf"^{re.escape(ERP_URL)}/api/v1/crm/quotes/\d+/deliver/$").mock(
            side_effect=self._deliver
        )
        be.router.get(f"{CRM_URL}/api/v1/integrations/smtp/ready").mock(
            side_effect=lambda r: (
                httpx.Response(self.smtp_ready, json={"code": "forbidden"})
                if isinstance(self.smtp_ready, int)
                else httpx.Response(200, json=self.smtp_ready)
            )
        )
        self.deal = erp_deal()

    def _deliver(self, request: httpx.Request) -> httpx.Response:
        self.erp_paths.append(request.url.path)
        if self.deliver_error is not None:
            status, code = self.deliver_error
            return httpx.Response(status, json={"detail": code})
        body = json.loads(request.content)
        self.delivered.append(body)
        if isinstance(self.erp_quote, dict):
            report = dict(self.erp_quote.get("send_report") or {})
            report["sent_via"] = [*report.get("sent_via", []), body["channel"]]
            report["skipped"] = [
                s for s in report.get("skipped", []) if s["channel"] != body["channel"]
            ]
            self.erp_quote = {**self.erp_quote, "status_code": "SENT", "send_report": report}
        return httpx.Response(200, json={"id": 1203})

    def _erp(self, request: httpx.Request, value: Any) -> httpx.Response:
        self.erp_paths.append(request.url.path)
        if isinstance(value, Exception):
            raise value
        if isinstance(value, int):
            return httpx.Response(value, json={"detail": "x"})
        return httpx.Response(200, json=value)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        tail = request.url.path.removeprefix("/api/v1/")
        if not (tail.startswith(("approvals", "documents/"))):
            return super()._handle(request)
        self.calls.append(request)
        bearer = request.headers.get("authorization", "").removeprefix("Bearer ")
        if bearer not in self.issued:
            return httpx.Response(
                401, json={"code": "UNAUTHORIZED", "message": "x", "source": "eds"}
            )
        if (request.method, tail) in self.overrides:
            return self.overrides[(request.method, tail)](request)
        if tail == "approvals":
            return self._list(request)
        match = re.fullmatch(r"approvals/([0-9a-f-]{36})(/decision)?", tail)
        if match:
            route = self.routes.get(match[1])
            if route is None:
                return httpx.Response(404, json=_error("NOT_FOUND", "Маршрут не найден."))
            if match[2]:
                return self._decide_route(route, json.loads(request.content))
            return httpx.Response(200, json=route)
        match = re.fullmatch(r"documents/([0-9a-f-]{36})", tail)
        doc = self.documents.get(match[1]) if match else None
        if doc is None:
            return httpx.Response(404, json=_error("NOT_FOUND", "Документ не найден."))
        return httpx.Response(200, json=doc)

    def _list(self, request: httpx.Request) -> httpx.Response:
        templates = request.url.params.get_list("template")
        key = "quote" if templates == ["quote"] else "memo"
        items = [list_item(self.routes[i]) for i in self.listing[key]]
        return httpx.Response(200, json={"items": items, "next_cursor": None})

    def _decide_route(self, route: dict[str, Any], body: dict[str, Any]) -> httpx.Response:
        if route["status"] != "open":
            return httpx.Response(
                409,
                json=_error("CONFLICT", "Маршрут уже закрыт.", reason="route_closed"),
            )
        failed = [c["code"] for c in route["checklist"] if c["blocking"] and not c["ok"]]
        if body["decision"] == "approve" and failed:
            return httpx.Response(
                409,
                json=_error(
                    "CONFLICT",
                    "Чек-лист не выполнен.",
                    reason="checklist_not_green",
                    failed=failed,
                ),
            )
        status = {"approve": "approved", "return": "returned", "reject": "rejected"}[
            body["decision"]
        ]
        outgoing = "ИСХ-031/26" if route["template"] == "quote" and status == "approved" else None
        done = {
            **route,
            "status": status,
            "can_decide": False,
            "allowed_decisions": [],
            "outgoing_number": outgoing,
            "steps": [
                {**s, "status": status if s["status"] == "current" else s["status"]}
                for s in route["steps"]
            ],
        }
        self.routes[route["id"]] = done
        return httpx.Response(200, json=done)


def _error(code: str, message: str, **details: Any) -> dict[str, Any]:
    return {"code": code, "message": message, "source": "eds", "details": details}
