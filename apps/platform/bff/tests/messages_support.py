"""CRM для тестов «Ждут ответа» (D1-1): ответы в форме `crm.yaml`, данные выдуманы.

`CrmMessagesFake` — одна ловушка respx на `/inbox`, `/team`, `/leads*`, `/reply-templates`,
`/kb/products`. Ответы по умолчанию — «всё в порядке»; тест подменяет ответ (`answer`, `error`),
журнал `calls` показывает, что и с каким токеном ушло в CRM.
"""

import json
import re
from collections.abc import Callable
from typing import Any

import httpx

from tests.backends import Backends
from tests.consts import CRM_URL

NOW = "2026-10-27T09:00:00Z"
EARLIER = "2026-10-27T08:48:00Z"
DUE = "2026-10-27T09:03:00Z"

DISPOSITION = "attachment; filename=\"_____.pdf\"; filename*=UTF-8''%D0%97.pdf"
Handler = Callable[[httpx.Request], httpx.Response]
_PATHS = re.escape(CRM_URL) + r"/api/v1/(inbox|team|leads/|reply-templates|kb/products)"


def escalation(**over: Any) -> dict[str, Any]:
    return {
        "id": 31,
        "priority": "hot",
        "status": "open",
        "reason_codes": ["price_or_contract_asked", "BAD CODE"],
        "reason_text": "Просит цену на 40 т",
        "recommendation": "Уточнить объём и прислать КП",
        "taken_by_user_id": None,
        "taken_at": None,
        "sla_due_at": DUE,
        "snoozed_until": None,
        "created_at": EARLIER,
        **over,
    }


def lead(lead_id: int = 2041, **over: Any) -> dict[str, Any]:
    return {
        "id": lead_id,
        "display_name": "Азиз Демо",
        "language": "ru",
        "stage": "handoff",
        "score": 70,
        "owner_mode": "paused",
        "assigned_user_id": None,
        "assigned_user_name": None,
        "client_id": None,
        "unread": False,
        "need_summary": "Рельсы Р65, 40 т",
        "product_interest": ["rails"],
        "last_lead_msg_at": EARLIER,
        "created_at": EARLIER,
        "escalation": escalation(),
        "source": "telegram",
        "handoff_note": {
            "request": "Рельсы Р65, 40 т",
            "facts": {
                "interest": ["Рельсы"],
                "timeline": "<3m",
                "decision_role": "decision_maker",
                "budget_hint": None,
                "company": "ООО Демо-Логистик",
                "company_size": None,
                "region": "unknown-code-is-text",
            },
            "reason_codes": ["price_or_contract_asked"],
            "reason_text": "Просит цену на 40 т",
            "recommendation": "Уточнить объём и прислать КП",
            "last_lead_message": "Сколько стоит?",
        },
        **over,
    }


def lead_detail(lead_id: int = 2041, **over: Any) -> dict[str, Any]:
    base = lead(lead_id)
    base.pop("handoff_note")
    return {
        **base,
        "handoff_note": None,
        "qualification": {"timeline": "<3m", "decision_role": "boss", "company": " ООО Демо "},
        "consent_given_at": EARLIER,
        "consent_method": None,
        "tg_username": "aziz_demo",
        "phone_e164": None,
        "email": None,
        "company_name": "ООО Демо-Логистик",
        "client_phone_e164": "+998900000000",
        "notes_count": 1,
        "snoozed_until": None,
        "open_service_request_id": None,
        "backoffice_mode": "erp",
        "erp_company_id": None,
        "erp_deal_id": None,
        "client_in_erp": False,
        "client_handoff_status": None,
        "client_handoff_error": None,
        **over,
    }


def message(message_id: int, role: str = "lead", **over: Any) -> dict[str, Any]:
    return {
        "id": message_id,
        "role": role,
        "text": f"Сообщение {message_id}",
        "attachments": [],
        "sent_by_user_id": 7 if role == "manager" else None,
        "created_at": EARLIER,
        "meta": {},
        **over,
    }


STORED = {
    "kind": "file",
    "name": "Заявка.pdf",
    "mime": "application/pdf",
    "size": 1200,
    "storage_key": "tg/5001/77/Заявка.pdf",
    "stored": True,
}
NOT_STORED = {"kind": "file", "name": "big.zip", "mime": "application/zip", "stored": False}


class CrmMessagesFake:
    def __init__(self, be: Backends) -> None:
        self.calls: list[httpx.Request] = []
        self.overrides: dict[tuple[str, str], Handler | httpx.Response] = {}
        be.router.route(url__regex=_PATHS).mock(side_effect=self._handle)

    def answer(self, method: str, path: str, status: int = 200, body: Any = None) -> None:
        self.overrides[(method, f"/api/v1/{path}")] = httpx.Response(status, json=body)

    def error(self, method: str, path: str, status: int, code: str, **details: Any) -> None:
        self.answer(method, path, status, {"code": code, "message": code, "details": details})

    def last(self, method: str, path: str) -> httpx.Request:
        found = [c for c in self.calls if c.method == method and c.url.path == f"/api/v1/{path}"]
        assert found, f"CRM не вызывали: {method} {path}"
        return found[-1]

    def body(self, method: str, path: str) -> Any:
        return json.loads(self.last(method, path).content)

    def to(self, path: str) -> list[httpx.Request]:
        return [c for c in self.calls if c.url.path == f"/api/v1/{path}"]

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        key = (request.method, request.url.path)
        if key in self.overrides:
            hit = self.overrides[key]
            return hit(request) if callable(hit) else hit
        return self._default(request)

    def _default(self, request: httpx.Request) -> httpx.Response:
        m, p = request.method, request.url.path.removeprefix("/api/v1/")
        action = {"id": None, "ok": True}
        mine = lead(2050, escalation=None, owner_mode="human", assigned_user_id=7, unread=True)
        table: dict[tuple[str, str], Any] = {
            ("GET", "inbox"): {
                "escalations": [lead(2041)],
                "mine": [mine, lead(2041)],
                "unassigned": [lead(2060, escalation=None, handoff_note=None)],
            },
            ("GET", "team"): [{"id": 7, "full_name": "Дилшод Менеджеров"}],
            ("GET", "kb/products"): [
                {"key": "rails", "name": "Рельсы", "description": None, "is_active": True}
            ],
            ("GET", "leads/2041"): lead_detail(2041),
            ("GET", "leads/2041/messages"): [
                message(90, attachments=[STORED, NOT_STORED]),
                message(91, "bot"),
                message(92, "manager"),
            ],
            ("GET", "leads/2041/notes"): [
                {
                    "id": 5,
                    "user_id": 7,
                    "text": "Клиент просил не звонить до обеда",
                    "visible_to_bot": False,
                    "created_at": NOW,
                }
            ],
            ("POST", "leads/2041/actions/take"): action,
            ("POST", "leads/2041/messages"): {"id": 93, "ok": True},
            ("POST", "leads/2041/actions/note"): {"id": 6, "ok": True},
            ("POST", "leads/2041/assist"): {
                "text": "Добрый день! Цену пришлём в КП сегодня.",
                "cost_usd": 0.001,
                "notice": None,
            },
            ("POST", "leads/2041/actions/return_to_bot"): action,
            ("GET", "reply-templates"): [
                {
                    "id": 1,
                    "title": "Приветствие",
                    "text": {"ru": "Здравствуйте, {name}!", "uz": "Salom!", "en": "Hello!"},
                    "updated_at": NOW,
                }
            ],
        }
        if (m, p) == ("GET", "leads/2041/messages/90/attachments/0"):
            return httpx.Response(
                200,
                content=b"%PDF-1.4 demo",
                headers={
                    "content-type": "application/pdf",
                    "content-disposition": DISPOSITION,
                },
            )
        if (m, p) in table:
            return httpx.Response(200, json=table[(m, p)])
        return httpx.Response(
            404, json={"code": "not_found", "message": "not found", "details": {}}
        )
