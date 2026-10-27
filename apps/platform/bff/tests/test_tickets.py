"""Обращения сотрудников к администратору (W15-H7, контракт 0.24.0) и колокольчик CRM.

CRM на respx: решения (темы, лимит, права, статусы) за CRM, здесь — перевод номеров `ОБР-0012`, роль
автора из сессии, права раздела `admin`, ошибки значений и лента CRM в колокольчике.
"""

import json
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from tests.backends import Backends
from tests.conftest import ContractChecker, Web
from tests.consts import CRM_URL

TICKETS = f"{CRM_URL}/api/v1/staff-tickets"
MINE = f"{CRM_URL}/api/v1/me/tickets"
NOW = datetime(2026, 10, 28, 9, 0, tzinfo=UTC).isoformat().replace("+00:00", "Z")


def crm_row(ticket_id: int = 12, **over: Any) -> dict[str, Any]:
    return {
        "id": ticket_id,
        "number": f"ОБР-{ticket_id:04d}",
        "subject": "access",
        "status": "new",
        "author_id": 7,
        "author_name": "Иван Тестов",
        "author_role": "Менеджер",
        "page": "/erp/calc",
        "preview": "Нужен доступ к «Расчёту»",
        "replies": 0,
        "created_at": NOW,
        "updated_at": NOW,
        **over,
    }


def crm_ticket(ticket_id: int = 12, **over: Any) -> dict[str, Any]:
    return {**crm_row(ticket_id), "body": "Нужен доступ к «Расчёту»", "messages": [], **over}


def error(status: int, code: str, reason: str | None = None, **details: Any) -> httpx.Response:
    body = {
        "code": code,
        "message": code,
        "details": {**({"reason": reason} if reason else {}), **details},
    }
    return httpx.Response(status, json=body)


class CrmTickets:
    def __init__(self, be: Backends) -> None:
        self.calls: list[tuple[str, str, Any]] = []
        self.reply: httpx.Response | None = None
        router = be.router
        router.post(MINE).mock(side_effect=lambda r: self._answer("create", r, 201, crm_ticket()))
        router.get(MINE).mock(side_effect=lambda r: self._answer("mine", r, 200, [crm_row()]))
        router.get(url__regex=rf"^{MINE}/\d+$").mock(
            side_effect=lambda r: self._answer("mine_one", r, 200, crm_ticket())
        )
        router.get(url__regex=rf"^{TICKETS}\?.*").mock(
            side_effect=lambda r: self._answer(
                "list",
                r,
                200,
                {
                    "items": [crm_row()],
                    "total": 1,
                    "counts": {"new": 1, "in_progress": 0, "resolved": 0},
                },
            )
        )
        router.get(url__regex=rf"^{TICKETS}/\d+$").mock(
            side_effect=lambda r: self._answer("one", r, 200, crm_ticket())
        )
        router.post(url__regex=rf"^{TICKETS}/\d+/reply$").mock(
            side_effect=lambda r: (
                self.reply
                or self._answer(
                    "reply",
                    r,
                    200,
                    crm_ticket(
                        status="in_progress",
                        replies=1,
                        messages=[
                            {
                                "id": 1,
                                "author_id": 9,
                                "author_name": "Админ",
                                "body": "ок",
                                "created_at": NOW,
                            }
                        ],
                    ),
                )
            )
        )
        router.post(url__regex=rf"^{TICKETS}/\d+/status$").mock(
            side_effect=lambda r: self._answer("status", r, 200, crm_ticket(status="resolved"))
        )

    def _answer(self, name: str, request: httpx.Request, status: int, body: Any) -> httpx.Response:
        payload = json.loads(request.content) if request.content else None
        self.calls.append((name, str(request.url), payload))
        return httpx.Response(status, json=body)

    def last(self, name: str) -> tuple[str, Any]:
        for call in reversed(self.calls):
            if call[0] == name:
                return call[1], call[2]
        raise AssertionError(f"нет вызова {name}")


@pytest.fixture
def crm(be: Backends) -> CrmTickets:
    return CrmTickets(be)


async def test_create_sends_the_role_from_the_session_and_hides_internal_ids(
    web: Web, crm: CrmTickets, check: ContractChecker
) -> None:
    await web.login(["MANAGER"])

    response = await web.send(
        "POST",
        "/api/v1/tickets",
        json={"subject": "access", "body": "Нужен доступ к «Расчёту»", "page": "/erp/calc"},
    )

    assert response.status_code == 201, response.text
    check(response, "/tickets", "post")
    body = response.json()
    assert body["number"] == "ОБР-0012"
    assert "id" not in body
    assert body["author"] == {"id": "7", "name": "Иван Тестов"}
    _, sent = crm.last("create")
    assert sent == {
        "subject": "access",
        "body": "Нужен доступ к «Расчёту»",
        "page": "/erp/calc",
        "role": "Менеджер",
    }


async def test_create_ignores_a_role_sent_by_the_browser(web: Web, crm: CrmTickets) -> None:
    await web.login(["MANAGER"])

    response = await web.send(
        "POST",
        "/api/v1/tickets",
        json={"subject": "error", "body": "Сбой", "role": "Администратор"},
    )

    assert response.status_code == 422  # extra=forbid: роль приходит только из сессии
    assert crm.calls == []


async def test_create_requires_csrf_and_a_known_subject(web: Web, crm: CrmTickets) -> None:
    await web.login(["MANAGER"])

    no_csrf = await web.send(
        "POST", "/api/v1/tickets", json={"subject": "error", "body": "x"}, csrf="wrong"
    )
    assert no_csrf.status_code == 403
    bad = await web.send("POST", "/api/v1/tickets", json={"subject": "bug", "body": "x"})
    assert bad.status_code == 422
    assert crm.calls == []


async def test_value_errors_of_crm_become_422_with_field_and_reason(
    web: Web, be: Backends, crm: CrmTickets, check: ContractChecker
) -> None:
    await web.login(["MANAGER"])
    be.router.post(MINE).mock(
        return_value=error(422, "validation_failed", "ticket_text_empty", field="body")
    )

    response = await web.send("POST", "/api/v1/tickets", json={"subject": "error", "body": " "})

    assert response.status_code == 422
    check(response, "/tickets", "post")
    body = response.json()
    assert body["code"] == "VALIDATION_FAILED"
    assert body["message"] == "Опишите, что случилось."
    assert body["details"] == {"fields": ["body"], "reason": "ticket_text_empty"}


async def test_rate_limit_is_translated_with_retry_after(
    web: Web, be: Backends, crm: CrmTickets, check: ContractChecker
) -> None:
    await web.login(["MANAGER"])
    be.router.post(MINE).mock(
        return_value=httpx.Response(
            429,
            headers={"Retry-After": "120"},
            json={
                "code": "rate_limited",
                "message": "x",
                "details": {"reason": "ticket_rate_limited"},
            },
        )
    )

    response = await web.send("POST", "/api/v1/tickets", json={"subject": "error", "body": "ещё"})

    assert response.status_code == 429
    check(response, "/tickets", "post")
    assert response.json()["code"] == "TOO_MANY_REQUESTS"
    assert response.json()["details"]["reason"] == "ticket_rate_limited"
    assert response.headers["retry-after"] == "120"


async def test_my_tickets_list_and_card_by_number(
    web: Web, crm: CrmTickets, check: ContractChecker
) -> None:
    await web.login(["MANAGER"])

    mine = await web.client.get("/api/v1/tickets")
    one = await web.client.get("/api/v1/tickets/ОБР-0012")

    check(mine, "/tickets", "get")
    check(one, "/tickets/{number}", "get")
    assert [t["number"] for t in mine.json()["items"]] == ["ОБР-0012"]
    assert one.json()["messages"] == []
    assert crm.last("mine_one")[0].endswith("/me/tickets/12")


async def test_card_with_a_bad_number_is_not_sent_to_crm(web: Web, crm: CrmTickets) -> None:
    await web.login(["MANAGER"])

    response = await web.client.get("/api/v1/tickets/12")

    assert response.status_code == 422
    assert crm.calls == []


async def test_foreign_ticket_is_not_found(web: Web, be: Backends, crm: CrmTickets) -> None:
    await web.login(["MANAGER"])
    be.router.get(url__regex=rf"^{MINE}/\d+$").mock(return_value=error(404, "not_found"))

    response = await web.client.get("/api/v1/tickets/ОБР-0099")

    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"


async def test_admin_list_passes_filters_and_checks_the_admin_section(
    web: Web, crm: CrmTickets, check: ContractChecker
) -> None:
    await web.login(["MANAGER"])
    forbidden = await web.client.get("/api/v1/admin/tickets")
    assert forbidden.status_code == 403
    assert crm.calls == []

    await web.login(["DIRECTOR"])  # директор читает
    response = await web.client.get(
        "/api/v1/admin/tickets", params={"status": "new", "subject": "access", "limit": 20}
    )

    assert response.status_code == 200, response.text
    check(response, "/admin/tickets", "get")
    assert response.json()["counts"] == {"new": 1, "in_progress": 0, "resolved": 0}
    url, _ = crm.last("list")
    assert "status=new" in url
    assert "subject=access" in url
    assert "limit=20" in url


async def test_only_admin_full_replies_and_changes_status(
    web: Web, crm: CrmTickets, check: ContractChecker
) -> None:
    await web.login(["DIRECTOR"])
    denied = await web.send("POST", "/api/v1/admin/tickets/ОБР-0012/reply", json={"body": "ок"})
    assert denied.status_code == 403
    denied_status = await web.send(
        "POST", "/api/v1/admin/tickets/ОБР-0012/status", json={"status": "resolved"}
    )
    assert denied_status.status_code == 403
    assert crm.calls == []

    await web.login(["ADMIN"])
    reply = await web.send(
        "POST", "/api/v1/admin/tickets/ОБР-0012/reply", json={"body": "ок", "status": "resolved"}
    )
    assert reply.status_code == 200, reply.text
    check(reply, "/admin/tickets/{number}/reply", "post")
    assert reply.json()["messages"][0]["author_name"] == "Админ"
    assert crm.last("reply")[1] == {"body": "ок", "status": "resolved"}

    status = await web.send(
        "POST", "/api/v1/admin/tickets/ОБР-0012/status", json={"status": "resolved"}
    )
    check(status, "/admin/tickets/{number}/status", "post")
    assert status.json()["status"] == "resolved"
    card = await web.client.get("/api/v1/admin/tickets/ОБР-0012")
    check(card, "/admin/tickets/{number}", "get")


async def test_status_transition_conflict_is_a_409_with_reason(
    web: Web, crm: CrmTickets, check: ContractChecker
) -> None:
    await web.login(["ADMIN"])
    crm.reply = error(409, "conflict", "ticket_status_transition")

    response = await web.send(
        "POST", "/api/v1/admin/tickets/ОБР-0012/reply", json={"body": "ок", "status": "new"}
    )

    assert response.status_code == 409
    check(response, "/admin/tickets/{number}/reply", "post")
    assert response.json()["code"] == "CONFLICT"
    assert response.json()["details"]["reason"] == "ticket_status_transition"


async def test_crm_down_is_a_503_on_create(web: Web, be: Backends, crm: CrmTickets) -> None:
    await web.login(["MANAGER"])
    be.router.post(MINE).mock(side_effect=httpx.ConnectError("down"))

    response = await web.send("POST", "/api/v1/tickets", json={"subject": "error", "body": "сбой"})

    assert response.status_code == 503
    assert response.json()["source"] == "crm"
