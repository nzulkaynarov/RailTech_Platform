"""Группы Telegram с секретарём (ТГ-1б, контракт BFF, тег `telegram-groups`): прокси к CRM.

CRM — на respx, ответы BFF сверяются со схемами platform-bff.yaml. Проверяется то, что делает
BFF: право (раздел `crm.clients`; 403 — до CRM), состояние группы из `status`, `access` и
`code_active`, нет кода привязки в ответе, тело привязки и отключения, группа клиента для карточки.
"""

import json
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from tests.backends import Backends
from tests.conftest import ContractChecker, Web
from tests.consts import CRM_URL
from tests.messages_support import NOT_STORED, STORED, CrmMessagesFake, message

BASE = "/api/v1/crm/telegram-groups"
NOW = datetime(2026, 11, 25, 9, 0, tzinfo=UTC).isoformat()


def group(chat_id: int, **over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "chat_id": chat_id,
        "title": f"Группа {chat_id}",
        "chat_type": "supergroup",
        "status": "pending",
        "access": "ok",
        "client_id": None,
        "client_name": None,
        "lead_id": None,
        "topic_mode": "request",
        "language": None,
        "code_active": True,
        "bound_at": None,
        "detected_at": NOW,
    }
    return row | over


BOUND = {"status": "bound", "client_id": 12, "client_name": "ТОО Рельс", "lead_id": 3001}


class CrmGroups:
    def __init__(self, be: Backends, rows: list[dict[str, Any]]) -> None:
        self.calls: list[httpx.Request] = []
        self.rows = rows
        be.router.route(url__regex=CRM_URL.replace(".", r"\.") + r"/api/v1/telegram-groups").mock(
            side_effect=self._handle
        )

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        path = request.url.path.removeprefix("/api/v1/telegram-groups")
        if request.method == "GET":
            return httpx.Response(200, json=self.rows)
        if path == "/bind":
            body = json.loads(request.content)
            if body["code"] == "WRONG1":
                return httpx.Response(
                    404, json={"code": "not_found", "message": "x", "details": {"reason": "bad"}}
                )
            return httpx.Response(200, json=group(-100, **BOUND, code_active=False))
        return httpx.Response(200, json={"id": None, "ok": True})


@pytest.fixture
def crm(be: Backends) -> CrmGroups:
    return CrmGroups(
        be,
        [
            group(-1),
            group(-2, code_active=False),
            group(-3, **BOUND),
            group(-4, **(BOUND | {"client_id": 13}), access="admin_required"),
            group(-5, status="unbound", client_id=14, client_name="Иной"),
            group(-6, status="removed"),
        ],
    )


async def test_list_derives_the_state_from_status_access_and_code(
    web: Web, crm: CrmGroups, check: ContractChecker
) -> None:
    await web.login(["MANAGER"])
    res = check(await web.client.get(BASE), "/crm/telegram-groups", "get")
    assert res.status_code == 200
    assert [i["state"] for i in res.json()["items"]] == [
        "waiting_code",
        "code_expired",
        "connected",
        "needs_admin",
        "disconnected",
        "removed",
    ]
    bound = res.json()["items"][2]
    assert bound["lead"] == "L-3001"
    assert bound["client_name"] == "ТОО Рельс"
    assert all("code" not in item and "code_active" not in item for item in res.json()["items"])


async def test_list_is_refused_before_crm_without_the_clients_section(
    web: Web, crm: CrmGroups
) -> None:
    await web.login(["ADMIN"])
    assert (await web.client.get(BASE)).status_code == 403
    assert crm.calls == []


async def test_bind_sends_code_and_client_and_refuses_without_the_right(
    web: Web, crm: CrmGroups, check: ContractChecker
) -> None:
    await web.login(["ADMIN"])  # без клиентов привязать нельзя
    assert (
        await web.send("POST", f"{BASE}/bind", json={"code": "ABC234", "client_id": 12})
    ).status_code == 403
    assert crm.calls == []
    await web.login(["MANAGER"])
    done = check(
        await web.send("POST", f"{BASE}/bind", json={"code": " ABC234 ", "client_id": 12}),
        "/crm/telegram-groups/bind",
        "post",
    )
    assert done.status_code == 200
    assert done.json()["state"] == "connected"
    assert json.loads(crm.calls[-1].content) == {"code": "ABC234", "client_id": 12}
    wrong = await web.send("POST", f"{BASE}/bind", json={"code": "WRONG1", "client_id": 12})
    assert wrong.status_code == 404


async def test_unbind_goes_to_crm_and_is_refused_without_the_right(
    web: Web, crm: CrmGroups, check: ContractChecker
) -> None:
    await web.login(["ADMIN"])
    assert (await web.send("POST", f"{BASE}/-1001234/unbind")).status_code == 403
    assert crm.calls == []
    await web.login(["MANAGER"])
    done = check(
        await web.send("POST", f"{BASE}/-1001234/unbind"),
        "/crm/telegram-groups/{chat_id}/unbind",
        "post",
    )
    assert done.status_code == 200
    assert (crm.calls[-1].method, crm.calls[-1].url.path) == (
        "POST",
        "/api/v1/telegram-groups/-1001234/unbind",
    )


async def test_client_group_is_the_bound_one_or_null(
    web: Web, crm: CrmGroups, check: ContractChecker
) -> None:
    await web.login(["ADMIN"])
    assert (await web.client.get("/api/v1/crm/clients/12/telegram-group")).status_code == 403
    await web.login(["MANAGER"])
    found = check(
        await web.client.get("/api/v1/crm/clients/12/telegram-group"),
        "/crm/clients/{id}/telegram-group",
        "get",
    )
    assert found.json()["group"]["chat_id"] == -3
    # отключённая и чужая группы клиента карточке не нужны
    for client in (14, 99):
        none = await web.client.get(f"/api/v1/crm/clients/{client}/telegram-group")
        assert none.json() == {"group": None}


async def test_group_feed_shows_staff_as_ours_and_the_reason_a_file_is_not_stored(
    web: Web, be: Backends, check: ContractChecker
) -> None:
    fake = CrmMessagesFake(be)
    fake.answer(
        "GET",
        "leads/3001/messages",
        body=[
            message(
                1,
                "lead",
                text="Смотрите файл",
                author_name="Алишер",
                meta={"author_name": "Алишер", "channel": "group"},
                channel="group",
                attachments=[
                    STORED,
                    {**NOT_STORED, "note": "файл больше 20 МБ — откройте в группе"},
                ],
            ),
            message(2, "manager", channel="group", meta={"channel": "group", "is_staff": True}),
        ],
    )
    fake.answer("GET", "leads/3001/notes", body=[])
    await web.login(["MANAGER"])
    res = check(
        await web.client.get("/api/v1/crm/messages/L-3001/thread"),
        "/crm/messages/{lead}/thread",
        "get",
    )
    first, second = res.json()["items"]
    assert [a["note"] for a in first["attachments"]] == [
        None,
        "файл больше 20 МБ — откройте в группе",
    ]
    assert first["attachments"][1]["url"] is None
    assert (first["author"], first["author_name"], first["channel"]) == ("lead", "Алишер", "group")
    assert (second["author"], second["channel"]) == ("manager", "group")
