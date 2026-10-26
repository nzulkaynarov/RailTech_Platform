"""CRM для тестов базы знаний и настроек бота (W13-A5): ответы в форме `crm.yaml`, данные выдуманы.

`CrmBotFake` — одна respx-ловушка на `/api/v1/kb*`, `/sandbox/*`, `/settings*`,
`/reply-templates*` и `/export/*`. Ответы по умолчанию — «всё в порядке»; тест подменяет
конкретный ответ через `answer()` или `error()`, а журнал `calls` показывает, что и с каким
токеном ушло в CRM.
"""

import json
import re
from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx

from tests.backends import Backends
from tests.consts import CRM_URL

NOW = "2026-10-26T09:00:00Z"
EARLIER = "2026-10-25T08:00:00Z"

CSV_LEADS = "﻿ID;Имя;Язык\r\n101;Анна Демо;ru\r\n102;Бахтиёр Демо;uz\r\n"


def document(doc_id: int = 1, **over: Any) -> dict[str, Any]:
    return {
        "id": doc_id,
        "title": f"Доставка и сроки {doc_id}",
        "product_key": "rails",
        "language": "ru",
        "source_type": "file",
        "mime": "text/markdown",
        "version": 1,
        "is_active": True,
        "ingest_status": "done",
        "ingest_error": None,
        "chunk_count": 4,
        "created_at": EARLIER,
        "updated_at": NOW,
        **over,
    }


def chunk(position: int = 0) -> dict[str, Any]:
    return {
        "id": 500 + position,
        "position": position,
        "heading_path": "Доставка > Сроки",
        "content": "Срок поставки рельсов — от 14 дней со дня оплаты (вымышленный пример).",
        "token_count": 21,
    }


def gap(gap_id: int = 1, **over: Any) -> dict[str, Any]:
    return {
        "id": gap_id,
        "lead_id": 2041,
        "question": "Есть ли гарантия на крепёж?",
        "language": "ru",
        "best_score": 0.41,
        "occurrences": 3,
        "status": "open",
        "resolved_document_id": None,
        "created_at": EARLIER,
        "updated_at": NOW,
        **over,
    }


def search_result(**over: Any) -> dict[str, Any]:
    return {
        "hits": [
            {
                "chunk_id": 500,
                "document_id": 1,
                "document_title": "Доставка и сроки 1",
                "heading_path": "Доставка > Сроки",
                "content": "Срок поставки рельсов — от 14 дней со дня оплаты.",
                "similarity": 0.83,
                "rrf_score": 0.031,
            }
        ],
        "best_score": 0.83,
        "min_score": 0.7,
        "confident": True,
        "language": "ru",
        **over,
    }


def sandbox_turn(**over: Any) -> dict[str, Any]:
    return {
        "replies": [{"text": "Срок поставки — от 14 дней.", "buttons": ["Передать менеджеру"]}],
        "why": {
            "decision": "answer",
            "reason": None,
            "best_score": 0.83,
            "documents": ["Доставка и сроки 1"],
            "triggers": [],
            "priority": None,
        },
        **over,
    }


def text3(ru: str, uz: str = "", en: str = "") -> dict[str, str]:
    return {"ru": ru, "uz": uz or ru, "en": en or ru}


def settings_response() -> dict[str, Any]:
    return {
        "values": {
            "company": {"name": "RailTech (демо)", "phone": "+998 00 000 00 00"},
            "texts": {"greeting": text3("Здравствуйте!", "Salom!", "Hello!")},
            "escalation": {"sla_minutes": 15, "reminder_minutes": 60},
        },
        "schemas": {
            "company": {"type": "object", "properties": {"name": {"type": "string"}}},
            "texts": {"type": "object", "properties": {"greeting": {"$ref": "#/$defs/L"}}},
            "escalation": {"type": "object", "properties": {"sla_minutes": {"type": "integer"}}},
        },
    }


def dry_run() -> dict[str, Any]:
    return {
        "dialogs": 50,
        "escalated_current": 12,
        "escalated_candidate": 9,
        "by_code_current": {"human_requested": 7, "complaint": 5},
        "by_code_candidate": {"human_requested": 7, "complaint": 2},
        "changed": [
            {
                "run_id": 31,
                "lead_id": 2041,
                "at": NOW,
                "current": ["complaint"],
                "candidate": [],
            }
        ],
    }


def template(template_id: int = 1, **over: Any) -> dict[str, Any]:
    return {
        "id": template_id,
        "title": "Пришлю КП сегодня",
        "text": text3("{name}, пришлю КП сегодня. {manager}", "", ""),
        "updated_at": NOW,
        **over,
    }


Handler = Callable[[httpx.Request], httpx.Response]
_API = re.escape(CRM_URL) + r"/api/v1/(kb|sandbox|settings|reply-templates|export)"


class Chunks(httpx.AsyncByteStream):
    """Тело ответа CRM кусками: помнит, сколько кусков отдано и закрыт ли ответ."""

    def __init__(self, parts: list[bytes]) -> None:
        self.parts = parts
        self.sent = 0
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for part in self.parts:
            self.sent += 1
            yield part

    async def aclose(self) -> None:
        self.closed = True


class CrmBotFake:
    """Ловушка respx для CRM: ответы по умолчанию + подмена на лету + журнал запросов."""

    def __init__(self, be: Backends) -> None:
        self.calls: list[httpx.Request] = []
        self.overrides: dict[tuple[str, str], Handler | httpx.Response] = {}
        self.streams: list[Chunks] = []
        self.route = be.router.route(url__regex=_API + r".*").mock(side_effect=self._handle)

    def answer(
        self, method: str, path: str, status: int = 200, body: Any = None, **kw: Any
    ) -> None:
        """Ответить на `METHOD /api/v1/<path>` заданным статусом и телом."""
        self.overrides[(method, f"/api/v1/{path}")] = httpx.Response(status, json=body, **kw)

    def error(
        self,
        method: str,
        path: str,
        status: int,
        code: str,
        reason: str | None = None,
        **details: Any,
    ) -> None:
        d = {**details, **({"reason": reason} if reason else {})}
        self.answer(method, path, status, {"code": code, "message": code, "details": d})

    def requests(self, method: str, path: str) -> list[httpx.Request]:
        return [r for r in self.calls if r.method == method and r.url.path == f"/api/v1/{path}"]

    def last(self, method: str, path: str) -> httpx.Request:
        found = self.requests(method, path)
        assert found, f"CRM не вызывали: {method} {path}"
        return found[-1]

    def body(self, method: str, path: str) -> Any:
        return json.loads(self.last(method, path).content)

    @property
    def count(self) -> int:
        return len(self.calls)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        key = (request.method, request.url.path)
        if key in self.overrides:
            hit = self.overrides[key]
            return hit(request) if callable(hit) else hit
        return self._default(request)

    def _default(self, request: httpx.Request) -> httpx.Response:
        def ok(body: Any, status: int = 200) -> httpx.Response:
            return httpx.Response(status, json=body)

        m, p = request.method, request.url.path.removeprefix("/api/v1/")
        action = {"id": None, "ok": True}
        table: dict[tuple[str, str], Any] = {
            ("GET", "kb/documents"): [document(1), document(2, is_active=False)],
            ("GET", "kb/gaps"): {"items": [gap(1), gap(2, occurrences=1)], "total": 2},
            ("GET", "kb/products"): [
                {"key": "rails", "name": "Рельсы", "description": None, "is_active": True}
            ],
            ("POST", "kb/search"): search_result(),
            ("POST", "sandbox/messages"): sandbox_turn(),
            ("GET", "settings"): settings_response(),
            ("POST", "settings/escalation/dry-run"): dry_run(),
            ("GET", "reply-templates"): [template(1), template(2, title="Спасибо за обращение")],
        }
        if (m, p) in table:
            return ok(table[(m, p)])
        if (m, p) in {("POST", "kb/documents"), ("POST", "kb/documents/manual")}:
            return ok({"id": 77}, 201)
        if (m, p) == ("POST", "reply-templates"):
            return ok({"id": 9}, 201)
        if (m, p) == ("POST", "sandbox/reset"):
            return httpx.Response(204)
        if m == "GET" and (found := re.fullmatch(r"kb/documents/(\d+)", p)):
            return ok(document(int(found[1])))
        if m == "GET" and (found := re.fullmatch(r"kb/documents/(\d+)/chunks", p)):
            return ok([chunk(0), chunk(1)])
        if m in {"PATCH", "POST"} and re.fullmatch(r"kb/documents/\d+(/reingest)?", p):
            return ok(action)
        if m == "POST" and re.fullmatch(r"kb/gaps/\d+/(resolve|ignore|reopen)", p):
            return ok(action)
        if m == "PUT" and re.fullmatch(r"settings/[a-z_]+", p):
            return ok(action)
        if m in {"PUT", "DELETE"} and re.fullmatch(r"reply-templates/\d+", p):
            return ok(action)
        if m == "GET" and (found := re.fullmatch(r"export/(leads|clients|deals)\.csv", p)):
            body = CSV_LEADS.encode("utf-8")
            stream = Chunks([body[:20], body[20:]])
            self.streams.append(stream)
            return httpx.Response(
                200,
                headers={
                    "content-type": "text/csv; charset=utf-8",
                    "content-disposition": f'attachment; filename="{found[1]}-20261026-1430.csv"',
                },
                stream=stream,
            )
        return httpx.Response(404, json={"code": "not_found", "message": "x", "details": {}})
