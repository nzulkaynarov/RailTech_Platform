"""EDS для тестов «Создать документ» и «Мои документы» (D1-5): ответы в форме `eds.yaml`, данные
выдуманы.

`EdsFake` — вход в EDS по SSO-токену CRM `aud=eds` (обмен в EDS) и одна respx-ловушка на `/api/v1/*`
EDS. Ответы
по умолчанию — «всё в порядке»; тест подменяет конкретный ответ через `answer()` или `error()`, а
журнал `calls`
показывает, что и с каким токеном ушло в EDS.
"""

import json
import re
from collections.abc import Callable
from typing import Any

import httpx

from tests.backends import Backends
from tests.consts import EDS_URL

NOW = "2026-10-27T09:00:00Z"
EARLIER = "2026-10-26T08:00:00Z"
DOC_ID = "10000000-0000-4000-8000-000000000001"
ROUTE_ID = "20000000-0000-4000-8000-000000000001"
FILE_ID = "30000000-0000-4000-8000-000000000001"
ME = {"crm_user_id": 7, "full_name": "Иван Тестов"}
DIRECTOR = {"crm_user_id": 3, "full_name": "Рустам Директоров"}
TOKEN = "eds-access-"


def money(amount: str = "1500000.00") -> dict[str, str]:
    return {"amount": amount, "currency": "UZS"}


def file_ref(file_id: str = FILE_ID, **over: Any) -> dict[str, Any]:
    return {
        "id": file_id,
        "name": "schet.pdf",
        "content_type": "application/pdf",
        "size": 2048,
        "version": 1,
        "sha256": "0" * 64,
        "uploaded_at": EARLIER,
        "uploaded_by": ME,
        **over,
    }


def document(doc_id: str = DOC_ID, **over: Any) -> dict[str, Any]:
    return {
        "id": doc_id,
        "kind": "memo",
        "number": "СЗ-2026/031",
        "status": "draft",
        "version": 1,
        "subject": "Закупка канцтоваров",
        "text": "Прошу согласовать закупку канцтоваров на квартал.",
        "author": ME,
        "addressee": None,
        "amount": None,
        "due_date": None,
        "files": [],
        "source_message_id": None,
        "erp_deal_id": None,
        "deal_number": None,
        "recipient": None,
        "in_reply_to": None,
        "approval_id": None,
        "decisions": [],
        "journal": [],
        "created_at": EARLIER,
        "updated_at": NOW,
        "archived_at": None,
        **over,
    }


def step(index: int, label: str, status: str, **over: Any) -> dict[str, Any]:
    return {
        "index": index,
        "label": label,
        "assignee": {"crm_user_id": None, "permission": "memos.approve"},
        "status": status,
        "decided_by": None,
        "decided_at": None,
        "comment": None,
        **over,
    }


def approval(steps: list[dict[str, Any]], **over: Any) -> dict[str, Any]:
    return {
        "id": ROUTE_ID,
        "template": "memo",
        "title": "СЗ-2026/031 · Закупка канцтоваров",
        "object": {"kind": "memo", "document_id": DOC_ID, "number": "СЗ-2026/031"},
        "status": "open",
        "round": 1,
        "steps": steps,
        "checklist": [],
        "quote": None,
        "can_decide": False,
        "allowed_decisions": [],
        "outgoing_number": None,
        "approved_late": False,
        "created_at": EARLIER,
        "closed_at": None,
        **over,
    }


def list_item(doc_id: str = DOC_ID, **over: Any) -> dict[str, Any]:
    return {
        "id": doc_id,
        "kind": "memo",
        "number": "СЗ-2026/031",
        "status": "on_approval",
        "subject": "Закупка канцтоваров",
        "author": ME,
        "amount": money(),
        "due_date": "2026-11-05",
        "created_at": EARLIER,
        **over,
    }


def registry_item(item_id: str = DOC_ID, **over: Any) -> dict[str, Any]:
    return {
        "kind": "memo",
        "id": item_id,
        "number": "СЗ-2026/031",
        "title": "Закупка канцтоваров",
        "status": "on_approval",
        "registered_at": EARLIER,
        "responsible": DIRECTOR,
        "client": None,
        "links": {},
        **over,
    }


Handler = Callable[[httpx.Request], httpx.Response]
_API = re.escape(EDS_URL) + r"/api/v1/.*"


class EdsFake:
    """Ловушка respx для EDS: вход по SSO, ответы по умолчанию, подмена на лету, журнал запросов."""

    def __init__(self, be: Backends) -> None:
        self.be = be
        self.sso_status = 200
        self.issued: list[str] = []
        self.calls: list[httpx.Request] = []
        self.overrides: dict[tuple[str, str], Handler | httpx.Response] = {}
        be.crm_sso.side_effect = self._sso
        self.exchange = be.router.post(f"{EDS_URL}/api/v1/auth/sso/exchange").mock(
            side_effect=self._exchange
        )
        self.route = be.router.route(url__regex=_API).mock(side_effect=self._handle)
        # `route` с общим шаблоном перехватил бы и обмен: порядок — по регистрации, обмен объявлен
        # раньше.

    # --- вход в EDS ---
    def _sso(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else {}
        if body.get("aud") != "eds":
            return httpx.Response(
                200, json={"token": "sso-token-1", "redirect_url": "http://erp.test/sso"}
            )
        if self.sso_status != 200:
            return httpx.Response(
                self.sso_status,
                json={
                    "code": "forbidden",
                    "message": "x",
                    "details": {"reason": "eds_access_denied"},
                },
            )
        return httpx.Response(
            200, json={"token": f"sso-eds-{len(self.issued) + 1}", "redirect_url": ""}
        )

    def _exchange(self, request: httpx.Request) -> httpx.Response:
        token = f"{TOKEN}{len(self.issued) + 1}"
        self.issued.append(token)
        return httpx.Response(
            200, json={"access_token": token, "token_type": "bearer", "expires_in": 900}
        )

    # --- подмена ответов ---
    def answer(
        self, method: str, path: str, status: int = 200, body: Any = None, **kw: Any
    ) -> None:
        self.overrides[(method, f"/api/v1/{path}")] = httpx.Response(status, json=body, **kw)

    def error(
        self,
        method: str,
        path: str,
        status: int,
        code: str,
        message: str = "Отказ EDS.",
        details: dict[str, Any] | None = None,
    ) -> None:
        body: dict[str, Any] = {"code": code, "message": message, "source": "eds"}
        if details:
            body["details"] = details
        self.answer(method, path, status, body)

    def validation(self, method: str, path: str, **fields: str) -> None:
        self.error(
            method,
            path,
            422,
            "VALIDATION_FAILED",
            "Сумма должна быть больше нуля.",
            {
                "fields": [
                    {"field": name, "message": text, "type": "value_error"}
                    for name, text in fields.items()
                ]
            },
        )

    def requests(self, method: str, path: str) -> list[httpx.Request]:
        return [r for r in self.calls if r.method == method and r.url.path == f"/api/v1/{path}"]

    def last(self, method: str, path: str) -> httpx.Request:
        found = self.requests(method, path)
        assert found, f"EDS не вызывали: {method} {path}"
        return found[-1]

    def body(self, method: str, path: str) -> Any:
        return json.loads(self.last(method, path).content)

    @property
    def count(self) -> int:
        return len(self.calls)

    # --- ответы по умолчанию ---
    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        bearer = request.headers.get("authorization", "").removeprefix("Bearer ")
        if bearer not in self.issued:
            return httpx.Response(
                401, json={"code": "UNAUTHORIZED", "message": "x", "source": "eds"}
            )
        key = (request.method, request.url.path)
        if key in self.overrides:
            hit = self.overrides[key]
            return hit(request) if callable(hit) else hit
        return self._default(request)

    def _default(self, request: httpx.Request) -> httpx.Response:
        def ok(body: Any, status: int = 200) -> httpx.Response:
            return httpx.Response(status, json=body)

        m, p = request.method, request.url.path.removeprefix("/api/v1/")
        if (m, p) == ("GET", "documents"):
            return ok({"items": [list_item()], "next_cursor": None})
        if (m, p) == ("GET", "registry"):
            return ok({"items": [registry_item()], "next_cursor": "cur-2"})
        if (m, p) == ("POST", "documents"):
            return ok(document(**{"kind": json.loads(request.content)["kind"]}), 201)
        if (m, p) == ("POST", "files"):
            return ok(file_ref(), 201)
        if m == "GET" and re.fullmatch(r"documents/[0-9a-f-]{36}", p):
            return ok(document(request.url.path.rsplit("/", 1)[1]))
        if m == "PATCH" and re.fullmatch(r"documents/[0-9a-f-]{36}", p):
            return ok(document(request.url.path.rsplit("/", 1)[1], **json.loads(request.content)))
        if m == "POST" and (found := re.fullmatch(r"documents/([0-9a-f-]{36})/submit", p)):
            return ok(document(found[1], status="on_approval", approval_id=ROUTE_ID))
        if m == "GET" and re.fullmatch(r"approvals/[0-9a-f-]{36}", p):
            return ok(
                approval(
                    [
                        step(1, "Директор", "current"),
                        step(
                            2,
                            "Бухгалтер",
                            "pending",
                            assignee={"crm_user_id": None, "permission": "payments.confirm"},
                        ),
                    ]
                )
            )
        if m == "GET" and re.fullmatch(r"files/[0-9a-f-]{36}", p):
            return httpx.Response(
                200,
                content=b"%PDF-1.4 demo",
                headers={
                    "content-type": "application/pdf",
                    "content-disposition": "attachment; filename*=UTF-8''schet.pdf",
                },
            )
        return httpx.Response(404, json={"code": "NOT_FOUND", "message": "x", "source": "eds"})
