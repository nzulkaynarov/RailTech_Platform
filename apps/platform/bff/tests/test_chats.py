"""Чаты · С клиентами и переписка отдельно от реестра лидов (B-D18-1, W18A-P3) — матрица ролей BFF.

CRM — на respx. BFF отсекает роли без `chats.external` и `crm.leads` (403 до CRM), карточку лида и
очередь «Ждут ответа» оставляет только `crm.leads`, а ленту и вложения диалога пропускает обоим
разделам — какой диалог открыт, решает CRM (чужой — 404, BFF не обходит). Ответы сверяются со
схемами platform-bff.yaml.
"""

from typing import Any

import httpx
import pytest

from tests.backends import Backends
from tests.conftest import ContractChecker, Web
from tests.consts import CRM_URL
from tests.messages_support import EARLIER, CrmMessagesFake

CHATS = "/api/v1/chats/external"
MESSAGES = "/api/v1/crm/messages"


def dialog(lead_id: int, access: str, **over: Any) -> dict[str, Any]:
    return {
        "lead_id": lead_id,
        "display_name": "Азиз Демо",
        "source": "telegram",
        "language": "ru",
        "client_id": 12,
        "assigned_user_id": 7,
        "last_lead_msg_at": EARLIER,
        "last_message_at": EARLIER,
        "invoiced": access == "invoiced",
        "access": access,
        **over,
    }


class CrmChats:
    """CRM `GET /chats`: ответ по умолчанию — один диалог зоны «Счета и оплаты»."""

    def __init__(self, be: Backends) -> None:
        self.calls: list[httpx.Request] = []
        self.body: Any = {"items": [dialog(2041, "invoiced")], "total": 1}
        self.status = 200
        be.router.get(f"{CRM_URL}/api/v1/chats").mock(side_effect=self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        return httpx.Response(self.status, json=self.body)


@pytest.fixture
def crm(be: Backends) -> CrmMessagesFake:
    return CrmMessagesFake(be)


@pytest.fixture
def chats(be: Backends) -> CrmChats:
    return CrmChats(be)


async def test_accountant_gets_the_dialogs_crm_opens_without_the_lead_registry(
    web: Web, crm: CrmMessagesFake, chats: CrmChats, check: ContractChecker
) -> None:
    await web.login(["ACCOUNTANT"])
    response = check(await web.client.get(f"{CHATS}?erp_deal_id=7301"), "/chats/external", "get")

    assert response.json() == {
        "items": [
            {
                "lead": "L-2041",
                "name": "Азиз Демо",
                "channel": "telegram",
                "language": "ru",
                "last_message_at": "2026-10-27T08:48:00Z",
                "assigned": {"id": "7", "name": "Дилшод Менеджеров", "initials": "ДМ"},
                "invoiced": True,
                "access": "invoiced",
            }
        ],
        "total": 1,
    }
    [call] = chats.calls
    assert call.url.params["erp_deal_id"] == "7301"
    assert call.headers["authorization"].startswith("Bearer crm-access-")
    # Данных реестра (оценка, квалификация) в ответе нет.
    assert "score" not in response.text
    assert "qualification" not in response.text


async def test_accountant_reads_the_thread_and_file_of_an_open_dialog(
    web: Web, crm: CrmMessagesFake, check: ContractChecker
) -> None:
    await web.login(["ACCOUNTANT"])
    thread = check(
        await web.client.get(f"{MESSAGES}/L-2041/thread"), "/crm/messages/{lead}/thread", "get"
    )
    assert [m["id"] for m in thread.json()["items"]] == [90, 91, 92, 94]
    file = await web.client.get(f"{MESSAGES}/L-2041/attachments/90/0")
    assert (file.status_code, file.content) == (200, b"%PDF-1.4 demo")


async def test_a_foreign_dialog_stays_closed_because_crm_decides(
    web: Web, crm: CrmMessagesFake
) -> None:
    """BFF не обходит объектную проверку CRM: её 404 — 404 экрану, без данных."""
    crm.error("GET", "leads/2041/messages", 404, "not_found")
    crm.error("GET", "leads/2041/messages/90/attachments/0", 404, "not_found")
    await web.login(["ACCOUNTANT"])
    for path in ("L-2041/thread", "L-2041/attachments/90/0"):
        response = await web.client.get(f"{MESSAGES}/{path}")
        assert response.status_code == 404, path
        assert response.json()["code"] == "NOT_FOUND"
    assert crm.to("leads/2041/messages")  # решение — у CRM, запрос ушёл


async def test_accountant_has_no_lead_registry_card_or_queue(
    web: Web, crm: CrmMessagesFake
) -> None:
    await web.login(["ACCOUNTANT"])
    for path in ("", "/L-2041"):
        response = await web.client.get(f"{MESSAGES}{path}")
        assert response.status_code == 403, path
        assert response.json()["details"] == {"resource": "crm.leads", "need": "read"}
    for action in ("take", "reply", "note", "assist", "return-to-bot"):
        response = await web.send("POST", f"{MESSAGES}/L-2041/{action}", json={"text": "x"})
        assert response.status_code == 403, action
    assert crm.calls == []


@pytest.mark.parametrize("role", ["MANAGER", "DIRECTOR"])
async def test_lead_registry_holders_list_dialogs_and_open_any_thread(
    web: Web, crm: CrmMessagesFake, chats: CrmChats, role: str
) -> None:
    chats.body = {"items": [dialog(2041, "registry"), dialog(2060, "registry")], "total": 2}
    await web.login([role])
    listed = (await web.client.get(CHATS)).json()
    assert [(i["lead"], i["access"]) for i in listed["items"]] == [
        ("L-2041", "registry"),
        ("L-2060", "registry"),
    ]
    assert (await web.client.get(f"{MESSAGES}/L-2041/thread")).status_code == 200
    assert (await web.client.get(f"{MESSAGES}/L-2041")).status_code == 200


@pytest.mark.parametrize("role", ["SUPPLY", "ENGINEER", "ADMIN"])
async def test_roles_without_client_chats_are_refused_before_crm(
    web: Web, crm: CrmMessagesFake, chats: CrmChats, role: str
) -> None:
    await web.login([role])
    response = await web.client.get(CHATS)
    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN"
    for path in ("L-2041/thread", "L-2041/attachments/90/0"):
        assert (await web.client.get(f"{MESSAGES}/{path}")).status_code == 403, path
    assert chats.calls == []
    assert crm.calls == []


async def test_crm_refusal_of_the_list_is_passed_on(web: Web, chats: CrmChats) -> None:
    """Роль поменяли в CRM, а профиль BFF ещё старый: отказ CRM — 403 экрану, не пустой список."""
    chats.status = 403
    chats.body = {"code": "forbidden", "message": "chats:read is not allowed", "details": {}}
    await web.login(["ACCOUNTANT"])
    response = await web.client.get(CHATS)
    assert response.status_code == 403
