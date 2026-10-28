"""CRM для тестов «Лиды», «Клиенты» и «Создать заявку» (W16-D1-2b): ответы в форме `crm.yaml`,
данные выдуманы.

`CrmLeadsFake` — одна ловушка respx на `/leads*`, `/team`, `/kb/products`, `/clients*`, `/deals*`,
`/documents`. Ответы по умолчанию — «всё в порядке»; тест подменяет ответ (`answer`, `error`),
журнал `calls` показывает, что и с какими параметрами ушло в CRM.
"""

import json
import re
from collections.abc import Callable
from typing import Any

import httpx

from tests.backends import Backends
from tests.consts import CRM_URL
from tests.messages_support import DISPOSITION, EARLIER, NOW, lead, lead_detail, message

Handler = Callable[[httpx.Request], httpx.Response]
_PATHS = re.escape(CRM_URL) + r"/api/v1/(leads|team|kb/products|clients|deals|documents)"
REQUEST_KEY = "40000000-0000-4000-8000-000000000001"
LETTER_ID = "30000000-0000-4000-8000-000000000001"
FUTURE = "2099-01-01T09:00:00Z"


def invitation_out(**over: Any) -> dict[str, Any]:
    return {
        "id": 3,
        "channel": "email",
        "status": "failed",
        "error": "no_email",
        "error_text": "У контакта нет почты",
        "sent_via": [],
        "sent_at": None,
        "created_at": EARLIER,
        "contact_id": 51,
        "contact_name": "Азиз Демо",
        "available_channels": ["telegram"],
        "suggested_channel": "telegram",
        "can_resend": True,
        **over,
    }


def notice_out(**over: Any) -> dict[str, Any]:
    return {
        "id": 4,
        "channel": "telegram",
        "status": "sent",
        "error": None,
        "error_text": None,
        "sent_at": EARLIER,
        "created_at": EARLIER,
        **over,
    }


def client_item(client_id: int = 12, **over: Any) -> dict[str, Any]:
    return {
        "id": client_id,
        "name": "ООО Демо-Логистик",
        "inn": "000000001",
        "segment": None,
        "owner_user_id": 7,
        "is_active": True,
        "notes": "внутренняя заметка",
        "created_at": EARLIER,
        "open_deals": 2,
        "last_activity_at": EARLIER,
        "erp_company_id": 501,
        "erp_handoff_status": "done",
        "erp_handoff_error": None,
        **over,
    }


def client_detail(client_id: int = 12, **over: Any) -> dict[str, Any]:
    return {
        "id": client_id,
        "name": "ООО Демо-Логистик",
        "inn": "000000001",
        "segment": "logistics",
        "owner_user_id": 7,
        "is_active": True,
        "notes": "внутренняя заметка",
        "created_at": EARLIER,
        "erp_company_id": 501,
        "erp_handoff_status": "done",
        "erp_handoff_error": None,
        "identities": [
            {
                "tg_user_id": 5001,
                "tg_username": "aziz_demo",
                "tg_first_name": "Азиз",
                "lead_id": 2041,
                "verified_at": EARLIER,
                "verified_by_user_id": 7,
            }
        ],
        "candidates": [],
        "leads": [
            {"id": 2041, "display_name": "Азиз Демо", "stage": "customer", "created_at": EARLIER}
        ],
        "service_requests": [],
        "invitation": invitation_out(status="sent", error=None, error_text=None, sent_at=NOW),
        **over,
    }


def contact(contact_id: int = 51, **over: Any) -> dict[str, Any]:
    return {
        "id": contact_id,
        "full_name": "Азиз Демо",
        "position": "Снабжение",
        "phone_e164": "+998900000000",
        "email": None,
        "telegram_identity_id": 9,
        "is_primary": True,
        "note": "звонить после обеда",
        "preferred_channel": "telegram",
        "created_at": EARLIER,
        **over,
    }


def deal(deal_id: int = 77, **over: Any) -> dict[str, Any]:
    return {
        "id": deal_id,
        "client_id": 12,
        "client_name": "ООО Демо-Логистик",
        "lead_id": 2041,
        "title": "Рельсы Р65",
        "product_key": "rails",
        "amount": None,
        "currency": "UZS",
        "stage": "open",
        "expected_close_date": None,
        "closed_at": None,
        "lost_reason": None,
        "owner_user_id": 7,
        "owner_name": "Дилшод Менеджеров",
        "created_at": EARLIER,
        "erp_deal_id": 900,
        "external_stage": "quote_sent",
        "erp_number": "ЗВ-2026-104",
        "request_summary": "Рельсы Р65, 40 т",
        "request_urgency": "urgent",
        "request_contact_id": 51,
        "request_letter_file_id": LETTER_ID,
        "erp_request_status": "done",
        "erp_request_error": None,
        **over,
    }


def document(doc_id: int = 61, **over: Any) -> dict[str, Any]:
    return {
        "id": doc_id,
        "client_id": 12,
        "type": "contract",
        "title": "Договор поставки",
        "number": "Д-17",
        "doc_date": "2026-10-20",
        "filename": "dogovor.pdf",
        "mime": "application/pdf",
        "size_bytes": 2048,
        "extract_status": "done",
        "is_visible_to_client": True,
        "created_at": EARLIER,
        **over,
    }


def created(**over: Any) -> dict[str, Any]:
    return {
        "client_id": 12,
        "deal_id": 77,
        "lead_id": 2041,
        "erp_request_status": "pending",
        "created": True,
        **over,
    }


def request_form(**over: Any) -> dict[str, Any]:
    return {
        "request_key": REQUEST_KEY,
        "lead": "L-2041",
        "client_id": None,
        "company": {"name": "ООО Демо-Логистик", "inn": None},
        "contact": {"full_name": "Азиз Демо", "phone": "+998900000000", "use_lead_telegram": True},
        "summary": "Рельсы Р65, 40 т",
        "urgency": "normal",
        "letter_file_id": LETTER_ID,
        "consent": {"method": "phone", "comment": "по звонку"},
        **over,
    }


class CrmLeadsFake:
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

    def params(self, method: str, path: str) -> dict[str, str]:
        return dict(self.last(method, path).url.params)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        key = (request.method, request.url.path)
        if key in self.overrides:
            hit = self.overrides[key]
            return hit(request) if callable(hit) else hit
        return self._default(request)

    def _default(self, request: httpx.Request) -> httpx.Response:
        m, p = request.method, request.url.path.removeprefix("/api/v1/")
        table: dict[tuple[str, str], Any] = {
            ("GET", "leads"): {
                "items": [
                    lead(2041, platform_status="wants_quote"),
                    lead(
                        2050,
                        escalation=None,
                        platform_status=None,
                        stage="customer",
                        client_id=12,
                        assigned_user_id=7,
                        assigned_user_name="Дилшод Менеджеров",
                        unread=True,
                        source="web",
                    ),
                ],
                "total": 42,
            },
            ("GET", "leads/2041"): lead_detail(
                2041,
                platform_status="wants_quote",
                client_id=12,
                consent_method="phone",
                confirmation=notice_out(),
                first_response_due_at=FUTURE,
                first_response_overdue=False,
                invitation=invitation_out(),
            ),
            ("GET", "leads/2041/messages"): [
                message(90, attachments=[{"storage_key": "tg/secret/key.pdf", "stored": True}]),
                message(91, "bot"),
                message(92, "manager"),
                message(93, "tool"),
                message(94, "lead", created_at=NOW),
            ],
            ("GET", "team"): [{"id": 7, "full_name": "Дилшод Менеджеров"}],
            ("GET", "kb/products"): [
                {"key": "rails", "name": "Рельсы", "description": None, "is_active": True}
            ],
            ("GET", "clients"): [
                client_item(13, name="ИП Тихий", last_activity_at=None, erp_company_id=None),
                client_item(12),
                client_item(14, name="АО Свежий", last_activity_at=NOW, erp_handoff_status=None),
            ],
            ("GET", "clients/12"): client_detail(12),
            ("GET", "clients/12/contacts"): {
                "contacts": [
                    contact(51),
                    contact(
                        52,
                        full_name="Ольга Почтова",
                        phone_e164=None,
                        email="olga@example.org",
                        telegram_identity_id=None,
                        is_primary=False,
                        preferred_channel="email",
                    ),
                ],
                "suggestions": [],
            },
            ("GET", "deals"): [
                deal(77),
                deal(
                    78,
                    title="Шпалы",
                    external_stage=None,
                    erp_number=None,
                    erp_deal_id=None,
                    erp_request_status="failed",
                    erp_request_error="erp_unreachable",
                    request_letter_file_id=None,
                    request_urgency=None,
                ),
                deal(79, title="Стрелки", external_stage="paid", erp_number="ПР-2026-007"),
                deal(80, title="Крепёж", stage="lost", external_stage="quote_sent"),
            ],
            ("GET", "documents"): [document(61), document(62, type="weird", doc_date=None)],
            ("POST", "clients/12/invitation"): invitation_out(
                channel="telegram", status="sent", sent_via=["telegram"], sent_at=NOW
            ),
            ("POST", "deals/78/actions/retry_request"): {
                "deal_id": 78,
                "client_id": 12,
                "erp_request_status": "pending",
            },
        }
        if (m, p) in (
            ("POST", "leads/2041/actions/create_request"),
            ("POST", "clients/12/actions/create_request"),
        ):
            return httpx.Response(201, json=created())
        if (m, p) == ("GET", "leads/2041/messages/90/attachments/0"):
            return httpx.Response(
                200,
                content=b"%PDF-1.4 demo",
                headers={"content-type": "application/pdf", "content-disposition": DISPOSITION},
            )
        if (m, p) in table:
            return httpx.Response(200, json=table[(m, p)])
        return httpx.Response(
            404, json={"code": "not_found", "message": "not found", "details": {}}
        )
