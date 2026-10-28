"""Клиенты · Лиды (W16-D1-2b, контракт BFF 0.27.0, тег `leads`): прокси к CRM.

CRM — на respx (`crm_leads_support`), ответы BFF сверяются со схемами platform-bff.yaml. Проверяется
то, что делает BFF: раздел `crm.leads` от чтения (403 — до CRM), вкладка, область и канал →
параметры CRM, словарь строки и карточки (статус CRM-02 и запасной по стадии, просрочка и открытая
передача, номер `L-NNNN`), последние сообщения без вложений и ключей хранилища, карточка без
сообщений и клиента при сбое CRM, 404 лида.
"""

import pytest

from tests.backends import Backends
from tests.conftest import ContractChecker, Web
from tests.crm_leads_support import CrmLeadsFake
from tests.messages_support import escalation, lead, lead_detail

BASE = "/api/v1/crm/leads"


@pytest.fixture
def crm(be: Backends) -> CrmLeadsFake:
    return CrmLeadsFake(be)


async def test_without_the_leads_section_the_list_is_forbidden_before_crm(
    web: Web, crm: CrmLeadsFake
) -> None:
    await web.login(["SUPPLY"])  # клиенты — да, лиды — нет
    assert (await web.client.get(BASE)).status_code == 403
    assert (await web.client.get(f"{BASE}/L-2041")).status_code == 403
    assert crm.calls == []


async def test_list_maps_rows_and_keeps_the_total_of_crm(
    web: Web, crm: CrmLeadsFake, check: ContractChecker
) -> None:
    await web.login(["DIRECTOR"])  # чтение
    response = check(await web.client.get(BASE), "/crm/leads", "get")

    page = response.json()
    assert page["total"] == 42
    first, second = page["items"]
    assert first == {
        "lead": "L-2041",
        "name": "Азиз Демо",
        "status": "wants_quote",
        "channel": "telegram",
        "language": "ru",
        "assigned": None,
        "need": "Рельсы Р65, 40 т",
        "last_message_at": "2026-10-27T08:48:00Z",
        "unread": False,
        "handoff_open": True,
        "overdue": True,  # срок передачи 2026-10-27 09:03 уже прошёл
        "client_id": None,
    }
    assert second["status"] == "client"  # CRM без platform_status — по стадии `customer`
    assert second["channel"] == "web"
    assert second["handoff_open"] is False
    assert second["overdue"] is False
    assert second["assigned"] == {"id": "7", "name": "Дилшод Менеджеров", "initials": "ДМ"}
    assert second["client_id"] == 12
    assert crm.params("GET", "leads") == {"offset": "0", "limit": "25"}
    assert crm.last("GET", "leads").headers["authorization"].startswith("Bearer crm-access-")


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("tab=new", {"platform_status": "new"}),
        ("tab=wants_quote&scope=mine", {"platform_status": "wants_quote", "owner": "me"}),
        ("tab=client&scope=overdue", {"platform_status": "client", "overdue": "true"}),
        ("channel=web&q=%20рельсы%20", {"source": "web", "q": "рельсы"}),
        ("offset=50&limit=100", {"offset": "50", "limit": "100"}),
    ],
)
async def test_tab_scope_and_channel_become_crm_filters(
    web: Web, crm: CrmLeadsFake, query: str, expected: dict[str, str]
) -> None:
    await web.login(["MANAGER"])
    assert (await web.client.get(f"{BASE}?{query}")).status_code == 200
    assert crm.params("GET", "leads") == {"offset": "0", "limit": "25", **expected}


async def test_bad_filters_are_422_before_crm(web: Web, crm: CrmLeadsFake) -> None:
    await web.login(["MANAGER"])
    for query in ("tab=lost", "scope=team", "channel=Web!", "limit=101", "offset=-1"):
        assert (await web.client.get(f"{BASE}?{query}")).status_code == 422, query
    assert crm.calls == []


async def test_snoozed_handoff_is_open_but_not_overdue(web: Web, crm: CrmLeadsFake) -> None:
    crm.answer(
        "GET",
        "leads",
        body={
            "items": [
                lead(2041, escalation=escalation(status="snoozed"), platform_status="dialog")
            ],
            "total": 1,
        },
    )
    await web.login(["MANAGER"])
    row = (await web.client.get(BASE)).json()["items"][0]
    assert (row["handoff_open"], row["overdue"]) == (True, False)


async def test_card_collects_contacts_facts_messages_and_d1_9_notices(
    web: Web, crm: CrmLeadsFake, check: ContractChecker
) -> None:
    await web.login(["DIRECTOR"])
    response = check(await web.client.get(f"{BASE}/l2041"), "/crm/leads/{lead}", "get")

    card = response.json()
    assert card["lead"] == "L-2041"
    assert card["status"] == "wants_quote"
    assert card["contacts"] == {
        "telegram": "aziz_demo",
        "phone": "+998900000000",
        "email": None,
        "company": "ООО Демо-Логистик",
    }
    assert card["consent"] == {"given_at": "2026-10-27T08:48:00Z", "method": "phone"}
    assert card["interest"] == ["Рельсы"]
    assert card["facts"]["interest"] == ["Рельсы"]
    assert card["facts"]["decision_role"] is None  # неизвестный код CRM не уходит
    assert card["handoff"]["state"] == "open"
    assert [m["author"] for m in card["last_messages"]] == [
        "lead",
        "bot",
        "manager",
        "system",
        "lead",
    ]
    assert card["client"] == {"id": 12, "name": "ООО Демо-Логистик", "inn": "000000001"}
    assert card["confirmation"] == {
        "channel": "telegram",
        "status": "sent",
        "sent_at": "2026-10-27T08:48:00Z",
        "error_text": None,
    }
    assert card["first_response"] == {"due_at": "2099-01-01T09:00:00Z", "overdue": False}
    assert card["invitation"]["status"] == "failed"
    assert card["invitation"]["suggested_channel"] == "telegram"
    assert crm.params("GET", "leads/2041/messages") == {"limit": "5"}
    text = response.text
    for leak in ("storage_key", "tg/secret", "внутренняя заметка", 'error"'):
        assert leak not in text


async def test_card_opens_without_messages_and_client_when_crm_fails(
    web: Web, crm: CrmLeadsFake, check: ContractChecker
) -> None:
    crm.answer("GET", "leads/2041/messages", 503, {"code": "unavailable"})
    crm.answer("GET", "clients/12", 503, {"code": "unavailable"})
    await web.login(["MANAGER"])
    card = check(await web.client.get(f"{BASE}/L-2041"), "/crm/leads/{lead}", "get").json()
    assert card["last_messages"] == []
    assert card["client"] == {"id": 12, "name": "ООО Демо-Логистик", "inn": None}


async def test_card_of_a_lead_without_client_and_notices(
    web: Web, crm: CrmLeadsFake, check: ContractChecker
) -> None:
    crm.answer("GET", "leads/2041", body=lead_detail(2041, stage="lost", platform_status=None))
    await web.login(["MANAGER"])
    card = check(await web.client.get(f"{BASE}/L-2041"), "/crm/leads/{lead}", "get").json()
    assert card["status"] == "lost"
    assert (card["client"], card["confirmation"], card["invitation"]) == (None, None, None)
    assert card["consent"]["method"] is None
    assert card["first_response"] == {"due_at": None, "overdue": False}
    assert crm.calls
    assert all(c.url.path != "/api/v1/clients/12" for c in crm.calls)


async def test_unknown_lead_is_404(web: Web, crm: CrmLeadsFake, check: ContractChecker) -> None:
    await web.login(["MANAGER"])
    response = check(await web.client.get(f"{BASE}/L-9999"), "/crm/leads/{lead}", "get")
    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"
