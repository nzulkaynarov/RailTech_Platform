"""EDS, ERP и справочник CRM для тестов «Входящие письма и резолюция» (D1-3): всё на respx.

EDS — по `eds.yaml` (`Letter`, `LetterPage`, `RegistryPage`, `ResolutionIn`): принимает только свой
токен доступа, который BFF получает обменом SSO-токена CRM `aud=eds`; ответы выдуманы. ERP отдаёт
сделку по `erp_deal_id`, CRM — `/users` и `/platform-roles` для кандидатов в исполнители.
"""

import json
import re
from collections.abc import Callable
from typing import Any

import httpx

from tests.backends import Backends
from tests.consts import CRM_URL, EDS_URL, ERP_URL

LETTER_ID = "20000000-0000-4000-8000-000000000104"
FILE_ID = "30000000-0000-4000-8000-000000000001"
NUMBER = "ВХ-104/26"
TOKEN = "eds-access-"

Answer = Callable[[httpx.Request], httpx.Response]


def person(user_id: int, name: str) -> dict[str, Any]:
    return {"crm_user_id": user_id, "full_name": name}


def letter(**over: Any) -> dict[str, Any]:
    """Письмо EDS `Letter` в статусе «Ждёт резолюции», связанное с заявкой ERP и клиентом CRM."""
    base: dict[str, Any] = {
        "id": LETTER_ID,
        "number": NUMBER,
        "status": "awaiting_resolution",
        "subject": "Запрос коммерческого предложения на стрелочные приводы",
        "summary": "Просим рассмотреть поставку 12 стрелочных приводов до конца квартала.",
        "sender": {"name": "ООО «Демо-Рейл»", "inn": "300123456", "contact": "Алия Демо"},
        "sender_ref": {"number": "исх-27", "date": "2026-10-22"},
        "received_at": "2026-10-24",
        "registered_at": "2026-10-24T09:15:00Z",
        "registered_by": None,
        "addressee": person(1, "Директор Демо"),
        "manager": person(2, "Менеджер Демо"),
        "urgent": True,
        "links": {
            "erp_request_id": 11,
            "erp_deal_id": 5,
            "deal_number": "ЗВ-2026-104",
            "crm_client_id": 42,
            "erp_company_id": 7,
        },
        "files": [
            {
                "id": FILE_ID,
                "name": "запрос.pdf",
                "content_type": "application/pdf",
                "size": 20480,
                "version": 1,
                "sha256": "a" * 64,
                "uploaded_at": "2026-10-24T09:14:00Z",
                "uploaded_by": person(2, "Менеджер Демо"),
            }
        ],
        "resolution": None,
        "return_comment": None,
        "reject_reason": None,
        "journal": [
            {
                "at": "2026-10-24T09:15:00Z",
                "action": "letter.registered",
                "by": None,
                "comment": None,
            }
        ],
    }
    return {**base, **over}


def resolved(**over: Any) -> dict[str, Any]:
    return letter(
        status="resolved",
        resolution={
            "text": "Посчитать с запасом по складу.",
            "assignees": [
                {"crm_user_id": 3, "zone": "goods", "full_name": "Снабженец Демо"},
                {"crm_user_id": 4, "zone": "services", "full_name": "Инженер Демо"},
            ],
            "due": "2026-10-30",
            "min_margin_pct": "15",
            "decided_by": person(1, "Директор Демо"),
            "decided_at": "2026-10-27T08:00:00Z",
        },
        **over,
    )


def deal(stage: str = "SOURCING", **over: Any) -> dict[str, Any]:
    return {
        "id": 5,
        "title": "Стрелочные приводы",
        "company_name": "ООО «Демо-Рейл»",
        "stage_code": stage,
        "execution_complete": False,
        "created_at": "2026-10-24T09:20:00Z",
        **over,
    }


def row(**over: Any) -> dict[str, Any]:
    source = letter()
    base = {
        key: source[key]
        for key in ("id", "number", "subject", "sender", "received_at", "status", "links", "urgent")
    }
    return {**base, "due": None, **over}


class EdsFake:
    """EDS с входом по SSO-токену CRM; маршруты письма, реестра и файлов; журнал запросов."""

    def __init__(self, be: Backends) -> None:
        self.be = be
        self.issued: list[str] = []
        self.exchange_status = 200
        self.sso_status = 200
        self.sso_auds: list[str] = []
        self.calls: list[httpx.Request] = []
        self.deal: dict[str, Any] | int | Exception | None = deal()
        self.erp_calls: list[httpx.Request] = []
        self.letters: dict[str, dict[str, Any]] = {LETTER_ID: letter()}
        self.registry: list[dict[str, Any]] = [
            {"kind": "letter_in", "id": LETTER_ID, "number": NUMBER}
        ]
        self.page: dict[str, Any] = {"items": [row()], "next_cursor": None}
        self.overrides: dict[tuple[str, str], Answer] = {}
        self.file_body = b"%PDF-1.7 demo"
        be.crm_sso.side_effect = self._sso
        self.exchange = be.router.post(f"{EDS_URL}/api/v1/auth/sso/exchange").mock(
            side_effect=self._exchange
        )
        be.router.route(url__regex=rf"^{re.escape(EDS_URL)}/api/v1/.*").mock(
            side_effect=self._handle
        )
        be.router.get(url__regex=rf"^{re.escape(ERP_URL)}/api/v1/crm/deals/\d+/$").mock(
            side_effect=self._deal
        )

    # --- вход ---
    def _sso(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else {}
        aud = body.get("aud", "erp")
        self.sso_auds.append(aud)
        if aud == "eds" and self.sso_status != 200:
            return httpx.Response(
                self.sso_status,
                json={
                    "code": "forbidden",
                    "message": "x",
                    "details": {"reason": "eds_access_denied"},
                },
            )
        return httpx.Response(
            200, json={"token": f"sso-{aud}-{len(self.sso_auds)}", "redirect_url": ""}
        )

    def _exchange(self, request: httpx.Request) -> httpx.Response:
        if self.exchange_status != 200:
            return httpx.Response(
                self.exchange_status,
                json={"code": "USER_NOT_PROVISIONED", "message": "x", "source": "eds"},
            )
        token = f"{TOKEN}{len(self.issued) + 1}"
        self.issued.append(token)
        return httpx.Response(
            200, json={"access_token": token, "token_type": "bearer", "expires_in": 900}
        )

    # --- ERP ---
    def _deal(self, request: httpx.Request) -> httpx.Response:
        self.erp_calls.append(request)
        if isinstance(self.deal, Exception):
            raise self.deal
        if isinstance(self.deal, int):
            return httpx.Response(self.deal, json={"detail": "x"})
        return httpx.Response(200, json=self.deal)

    # --- EDS ---
    def answer(self, method: str, tail: str, response: Answer | httpx.Response) -> None:
        """Подменить ответ EDS на `METHOD /api/v1/<tail>` (tail — путь с уже подставленным id)."""
        self.overrides[(method, tail)] = (
            (lambda _r: response) if isinstance(response, httpx.Response) else response
        )

    def made(self, method: str, tail: str) -> list[httpx.Request]:
        return [r for r in self.calls if r.method == method and r.url.path == f"/api/v1/{tail}"]

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        bearer = request.headers.get("authorization", "").removeprefix("Bearer ")
        if bearer not in self.issued:
            return httpx.Response(
                401, json={"code": "UNAUTHORIZED", "message": "x", "source": "eds"}
            )
        tail = request.url.path.removeprefix("/api/v1/")
        if (request.method, tail) in self.overrides:
            return self.overrides[(request.method, tail)](request)
        if request.method == "GET" and tail == "letters":
            return httpx.Response(200, json=self.page)
        if request.method == "GET" and tail == "registry":
            number = request.url.params.get("number")
            items = [i for i in self.registry if i["number"] == number]
            return httpx.Response(200, json={"items": items, "next_cursor": None})
        match = re.fullmatch(r"letters/([0-9a-f-]{36})(?:/(resolution|return|reject))?", tail)
        if match:
            found = self.letters.get(match[1])
            if found is None:
                return httpx.Response(
                    404,
                    json={"code": "NOT_FOUND", "message": "Письмо не найдено.", "source": "eds"},
                )
            if match[2] is None:
                return httpx.Response(200, json=found)
            return httpx.Response(
                200, json=self._decide(found, match[2], json.loads(request.content))
            )
        if request.method == "GET" and tail.startswith("files/"):
            if tail.removeprefix("files/") != FILE_ID:
                return httpx.Response(
                    404, json={"code": "NOT_FOUND", "message": "Файл не найден.", "source": "eds"}
                )
            return httpx.Response(
                200,
                content=self.file_body,
                headers={
                    "content-type": "text/html",
                    "content-disposition": "attachment; filename*=UTF-8''%D0%B7.pdf",
                },
            )
        return httpx.Response(404, json={"code": "NOT_FOUND", "message": "x", "source": "eds"})

    @staticmethod
    def _decide(found: dict[str, Any], action: str, body: dict[str, Any]) -> dict[str, Any]:
        if action == "resolution":
            return {
                **found,
                "status": "resolved",
                "resolution": {
                    "text": body["text"],
                    "assignees": [
                        {**a, "full_name": f"Сотрудник {a['crm_user_id']}"}
                        for a in body["assignees"]
                    ],
                    "due": body["due"],
                    "min_margin_pct": body.get("min_margin_pct"),
                    "decided_by": person(1, "Директор Демо"),
                    "decided_at": "2026-10-27T08:00:00Z",
                },
            }
        if action == "return":
            return {**found, "status": "returned", "return_comment": body["comment"]}
        return {**found, "status": "rejected", "reject_reason": body["reason"]}


def eds_error_body(code: str, message: str, **details: Any) -> dict[str, Any]:
    return {"code": code, "message": message, "source": "eds", "details": details}


# --- справочник CRM для кандидатов ---------------------------------------------------------


def crm_user(
    user_id: int,
    name: str,
    role_ids: list[int],
    *,
    active: bool = True,
    position: str | None = None,
) -> dict[str, Any]:
    return {
        "id": user_id,
        "email": f"user{user_id}@example.org",
        "full_name": name,
        "is_active": active,
        "platform_role_ids": role_ids,
        "position": position,
    }


def crm_role(role_id: int, access: dict[str, str]) -> dict[str, Any]:
    return {"id": role_id, "name": f"Роль {role_id}", "access": access}


class CrmDirectory:
    """`GET /users` и `GET /platform-roles` CRM для проверки зон исполнителей."""

    def __init__(self, be: Backends) -> None:
        self.users: list[dict[str, Any]] = []
        self.roles: list[dict[str, Any]] = []
        self.status: int | Exception = 200
        self.calls: list[httpx.Request] = []
        be.router.get(f"{CRM_URL}/api/v1/users").mock(side_effect=self._users)
        be.router.get(f"{CRM_URL}/api/v1/platform-roles").mock(side_effect=self._roles)

    def _answer(self, request: httpx.Request, body: list[dict[str, Any]]) -> httpx.Response:
        self.calls.append(request)
        if isinstance(self.status, Exception):
            raise self.status
        if self.status != 200:
            return httpx.Response(
                self.status, json={"code": "forbidden", "message": "x", "details": {}}
            )
        return httpx.Response(200, json=body)

    def _users(self, request: httpx.Request) -> httpx.Response:
        return self._answer(request, self.users)

    def _roles(self, request: httpx.Request) -> httpx.Response:
        return self._answer(request, self.roles)
