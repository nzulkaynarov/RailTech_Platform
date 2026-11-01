"""«Передать менеджеру» первой линией (D17G-1, DECISIONS 2026-11-01 п. 1): BFF.

Делопроизводитель (`crm.leads` — чтение, `crm.leads.triage` — полный) видит «Ждут ответа» и в «Моих
задачах» строки «Разобрать лида», передаёт лида менеджеру с запиской; «Забрать», ответ и «Вернуть
боту» ему закрыты до CRM. Менеджер-универсал видит строку «Новый лид от делопроизводителя» с
запиской только у себя; колокольчик ведёт в диалог. CRM — на respx, ответы сверяются с контрактом.
"""

from typing import Any

import pytest

from tests.backends import Backends
from tests.conftest import ContractChecker, Web
from tests.feeds_support import FeedBackends, Moments, escalation, lead
from tests.messages_support import CrmMessagesFake
from tests.messages_support import escalation as crm_escalation
from tests.messages_support import lead as crm_lead
from tests.roles import rid

BASE = "/api/v1/crm/messages"
NOTE = "Нужен расчёт 40 шпал к 15.11, звонить после обеда"


def handed(user_id: int, **over: Any) -> dict[str, Any]:
    """Передача первой линии: причина `handed_over`, записка, кто передал."""
    return {
        **escalation(reason=NOTE),
        "reason_codes": ["handed_over"],
        "handed_by_user_id": 12,
        "handed_by_user_name": "Камила Делопроизводитель",
        "request_type": "goods",
        **over,
    }


def assigned(row: dict[str, Any], user_id: int) -> dict[str, Any]:
    return {**row, "assigned_user_id": user_id, "owner_mode": "paused"}


# --- «Мои задачи» -------------------------------------------------------------------------------


@pytest.fixture
def fb(web: Web) -> FeedBackends:
    return FeedBackends(web.be.router, Moments(web.clock))


async def test_registrar_triages_free_leads_and_never_sees_handed_ones(
    web: Web, fb: FeedBackends, check: ContractChecker
) -> None:
    m = fb.m
    fb.state["inbox"] = {
        "escalations": [
            lead(2041, "Демо Клиентов", escalation=escalation(sla_due_at=m.ahead(hours=1))),
            # уже передан менеджеру — у первой линии строки нет
            assigned(lead(2045, "Передан", escalation=handed(7)), 7),
        ],
        "mine": [],
        "unassigned": [lead(2060, "Свободный", created=m.ago(hours=1))],
    }
    await web.login(["REGISTRAR"])

    response = check(await web.client.get("/api/v1/queue"), "/queue", "get")

    items = response.json()["items"]
    assert [(i["object"]["number"], i["kind"]) for i in items] == [
        ("L-2041", "triage_lead"),
        ("L-2060", "triage_lead"),
    ]
    assert items[0]["title"] == "Разобрать лида L-2041"
    assert items[0]["role_id"] == rid("REGISTRAR")
    assert items[0]["object"]["path"] == "/crm/messages?lead=L-2041"

    cards = check(await web.client.get("/api/v1/queue/cards"), "/queue/cards", "get").json()
    # «Проекты в работе» — от раздела «Проекты» (чтение) делопроизводителя
    assert {c["key"]: c["count"] for c in cards["cards"]} == {
        "leads_to_triage": 2,
        "projects_in_work": 0,
    }
    counters = (await web.client.get("/api/v1/menu-counters")).json()["items"]
    messages = [c for c in counters if (c["module"], c["section"]) == ("crm", "messages")]
    assert [(c["count"], c["attention"]) for c in messages] == [(2, True)]


async def test_manager_gets_the_handed_lead_with_the_note_and_others_do_not(
    web: Web, fb: FeedBackends
) -> None:
    fb.state["inbox"] = {
        "escalations": [
            assigned(lead(2045, "Азиз Демо", escalation=handed(7)), 7),
            assigned(lead(2046, "Чужой", escalation=handed(99)), 99),
        ],
        "mine": [],
        "unassigned": [],
    }
    await web.login(["MANAGER_ALL"])

    items = (await web.client.get("/api/v1/queue")).json()["items"]

    assert [(i["object"]["number"], i["kind"]) for i in items] == [("L-2045", "take_lead")]
    row = items[0]
    assert row["title"] == "Новый лид от делопроизводителя L-2045"
    assert NOTE[:40] in row["subtitle"]
    assert "передал(а) Камила Делопроизводитель" in row["subtitle"]
    assert row["object"]["path"] == "/crm/messages?lead=L-2045"


async def test_lead_notification_opens_the_conversation(web: Web, fb: FeedBackends) -> None:
    fb.state["crm_notifications"] = {
        "items": [
            {
                "id": 9,
                "kind": "lead_handed_over",
                "tab": "decisions",
                "title": "Новый лид от делопроизводителя L-2045",
                "subtitle": NOTE,
                "object_kind": "lead",
                "object_id": "2045",
                "object_number": "L-2045",
                "created_at": fb.m.ago(minutes=1),
                "read": False,
            }
        ],
        "unread_count": 1,
    }
    await web.login(["MANAGER_ALL"])

    page = (await web.client.get("/api/v1/notifications")).json()

    (note,) = [n for n in page["items"] if n["id"] == "crm:9"]
    assert note["tab"] == "decisions"
    assert note["object"] == {
        "kind": "lead",
        "number": "L-2045",
        "path": "/crm/messages?lead=L-2045",
    }


# --- «Ждут ответа» ------------------------------------------------------------------------------


@pytest.fixture
def crm(be: Backends) -> CrmMessagesFake:
    return CrmMessagesFake(be)


async def test_registrar_reads_the_inbox_and_hands_over_but_never_answers(
    web: Web, crm: CrmMessagesFake, check: ContractChecker
) -> None:
    crm.answer(
        "GET",
        "leads/handover_targets",
        body=[{"id": 7, "full_name": "Дилшод Менеджеров", "initials": "ДМ", "position": None}],
    )
    crm.answer("POST", "leads/2041/actions/hand_over", body={"id": None, "ok": True})
    await web.login(["REGISTRAR"])

    assert check(await web.client.get(BASE), "/crm/messages", "get").status_code == 200
    managers = check(await web.client.get("/api/v1/crm/lead-managers"), "/crm/lead-managers", "get")
    assert managers.json() == {
        "items": [{"id": "7", "name": "Дилшод Менеджеров", "initials": "ДМ"}]
    }

    body = {"user_id": "7", "note": NOTE, "request_type": "goods"}
    done = check(
        await web.send("POST", f"{BASE}/L-2041/hand-over", json=body),
        "/crm/messages/{lead}/hand-over",
        "post",
    )
    assert done.status_code == 200
    assert crm.body("POST", "leads/2041/actions/hand_over") == {
        "user_id": 7,
        "note": NOTE,
        "request_type": "goods",
    }
    assert (
        await web.send("POST", f"{BASE}/L-2041/hand-over", json={**body, "note": ""})
    ).status_code == 422

    for path, payload in (
        ("take", None),
        ("reply", {"text": "Добрый день", "client_message_id": "draft-0001"}),
        ("return-to-bot", None),
    ):
        refused = await web.send("POST", f"{BASE}/L-2041/{path}", json=payload)
        assert refused.status_code == 403, path
    assert not [c for c in crm.calls if c.method == "POST" and "hand_over" not in c.url.path]


async def test_hand_over_refusals_come_from_crm_and_managers_cannot_hand_over(
    web: Web, crm: CrmMessagesFake
) -> None:
    await web.login(["REGISTRAR"])
    crm.error(
        "POST",
        "leads/2041/actions/hand_over",
        409,
        "conflict",
        reason="lead_taken",
        assigned_user_name="Камила Демо",
    )
    taken = await web.send("POST", f"{BASE}/L-2041/hand-over", json={"user_id": "7", "note": NOTE})
    assert (taken.status_code, taken.json()["details"]["reason"]) == (409, "lead_taken")
    assert taken.json()["details"]["assigned_user_name"] == "Камила Демо"

    await web.login(["MANAGER_ALL"])
    response = await web.send(
        "POST", f"{BASE}/L-2041/hand-over", json={"user_id": "7", "note": NOTE}
    )
    assert response.status_code == 403
    assert response.json()["details"] == {"resource": "crm.leads.triage", "need": "full"}
    assert (await web.client.get("/api/v1/crm/lead-managers")).status_code == 403


async def test_the_handoff_names_who_handed_it_over(
    web: Web, crm: CrmMessagesFake, check: ContractChecker
) -> None:
    crm.answer(
        "GET",
        "inbox",
        body={
            "escalations": [
                crm_lead(
                    2041,
                    assigned_user_id=7,
                    escalation=crm_escalation(
                        reason_codes=["price_or_contract_asked", "handed_over"],
                        reason_text=NOTE,
                        handed_by_user_id=12,
                        handed_by_user_name="Камила Делопроизводитель",
                        request_type="goods",
                    ),
                )
            ],
            "mine": [],
            "unassigned": [],
        },
    )
    await web.login(["MANAGER_ALL"])

    item = check(await web.client.get(BASE), "/crm/messages", "get").json()["items"][0]

    assert item["handoff"]["reasons"] == ["price_or_contract_asked", "handed_over"]
    assert item["handoff"]["reason_text"] == NOTE
    assert item["handoff"]["handed_by"] == {
        "id": "12",
        "name": "Камила Делопроизводитель",
        "initials": "КД",
    }
    assert item["handoff"]["request_type"] == "goods"
    assert item["assigned"]["id"] == "7"
