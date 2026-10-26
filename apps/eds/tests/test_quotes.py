"""КП на одобрение (EDS-03, pg): событие ERP → маршрут «КП», чек-лист на сервере, ИСХ в решении, возврат, версии."""

from typing import Any

import httpx
import pytest
from sqlalchemy import text

from app.container import Container
from tests.domain import Person, deliver_erp, erp_event, outbox, validate
from tests.test_api_auth import assert_error

pytestmark = pytest.mark.pg

RESOLUTION = {
    "text": "Рассчитать",
    "assignees": [{"crm_user_id": 11, "zone": "goods"}, {"crm_user_id": 12, "zone": "services"}],
    "due": "2026-10-30",
}


async def ready(client: httpx.AsyncClient, container: Container, **payload: Any) -> str | None:
    """Доставить `quote.ready_for_approval` (пример контракта с подменой полей снимка)."""
    return await deliver_erp(client, container, erp_event("erp/quote.ready_for_approval.v1", **payload))


async def only_route(client: httpx.AsyncClient, who: Person, **params: Any) -> dict[str, Any]:
    page = (await client.get("/api/v1/approvals", params=params, headers=who.headers)).json()
    validate("ApprovalPage", page)
    [item] = page["items"]
    detail = await client.get(f"/api/v1/approvals/{item['id']}", headers=who.headers)
    assert detail.status_code == 200, detail.text
    body: dict[str, Any] = detail.json()
    validate("Approval", body)
    return body


async def resolve_letter(client: httpx.AsyncClient, staff: dict[str, Person], margin: str | None) -> dict[str, Any]:
    """Письмо по сделке 905 (как в примере КП) с резолюцией и порогом маржи."""
    created = await client.post(
        "/api/v1/letters",
        json={
            "subject": "Запрос",
            "summary": "Суть",
            "sender": {"name": "ООО «Пример Логистик»"},
            "received_at": "2026-10-25",
            "links": {"erp_request_id": 77, "erp_deal_id": 905, "deal_number": "ЗВ-2026-104"},
        },
        headers=staff["registrar"].headers,
    )
    letter: dict[str, Any] = created.json()
    done = await client.post(
        f"/api/v1/letters/{letter['id']}/resolution",
        json={**RESOLUTION, "min_margin_pct": margin},
        headers=staff["director"].headers,
    )
    assert done.status_code == 200, done.text
    return letter


async def test_event_opens_quote_route_with_snapshot_and_requested_event(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    assert await ready(client, container) == "processed"
    route = await only_route(client, staff["director"])
    assert (route["template"], route["status"], route["round"]) == ("quote", "open", 1)
    assert route["title"] == "КП-2026/115 v2 · ЗВ-2026-104"
    assert route["object"] == {
        "kind": "quote",
        "erp_quote_id": 1203,
        "quote_number": "КП-2026/115",
        "quote_version": 2,
        "erp_deal_id": 905,
        "deal_number": "ЗВ-2026-104",
    }
    assert route["steps"][0]["assignee"] == {"crm_user_id": None, "permission": "approvals.decide"}
    assert route["quote"]["margin_pct"] == "17.6" and route["quote"]["cost"] == "103000000.00"
    assert route["can_decide"] is True

    [requested] = await outbox(container, "approval.requested")
    assert requested["subject"] == "КП-2026/115"
    assert requested["data"]["approval"]["object"]["quote_version"] == 2
    assert requested["data"]["actor"] == {"type": "system"}


async def test_quote_event_is_idempotent_by_quote_and_version(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    await ready(client, container)
    await ready(client, container)  # другое событие (новый id), та же версия КП
    async with container.session_factory() as session:
        count = (await session.execute(text("SELECT count(*) FROM approval_routes"))).scalar_one()
    assert count == 1
    assert len(await outbox(container, "approval.requested")) == 1


async def test_green_checklist_allows_approval_with_outgoing_number_and_channels(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    await resolve_letter(client, staff, "15")
    await ready(client, container, eds_letter_id=None)
    route = await only_route(client, staff["director"])
    assert [(i["code"], i["ok"], i["blocking"]) for i in route["checklist"]] == [
        ("visa_goods", True, True),
        ("visa_services", True, True),
        ("margin", True, True),
        ("due", True, False),
    ]
    margin = next(i for i in route["checklist"] if i["code"] == "margin")
    assert margin["value"] == "17.6 % ≥ 15 %"
    visa = next(i for i in route["checklist"] if i["code"] == "visa_goods")
    assert visa["by"] == {"crm_user_id": 11, "full_name": "Сардор Снабженцев"} and visa["at"]
    assert route["allowed_decisions"] == ["approve", "return", "reject"]

    approved = await client.post(
        f"/api/v1/approvals/{route['id']}/decision",
        json={"decision": "approve", "channels": ["telegram", "cabinet"]},
        headers=staff["director"].headers,
    )
    assert approved.status_code == 200, approved.text
    body = approved.json()
    validate("Approval", body)
    assert (body["status"], body["outgoing_number"], body["allowed_decisions"]) == ("approved", "ИСХ-001/26", [])
    [decided] = await outbox(container, "approval.decided")
    data = decided["data"]
    assert (data["decision"], data["route_status"], data["outgoing_number"]) == ("approve", "approved", "ИСХ-001/26")
    assert data["channels"] == ["telegram", "cabinet"] and data["comment"] is None
    assert data["approval"]["object"]["erp_quote_id"] == 1203 and data["approval"]["object"]["quote_version"] == 2
    assert data["decided_by"] == {"crm_user_id": 3, "full_name": "Рустам Директоров"}
    assert decided["subject"] == "КП-2026/115"


async def test_margin_below_resolution_threshold_blocks_approval_on_server(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    """Порог — из резолюции EDS (20 %), а не из `min_margin_pct` события ERP (15 %): маржа 17.6 % — красная строка."""
    letter = await resolve_letter(client, staff, "20")
    await ready(client, container, eds_letter_id=letter["id"])
    route = await only_route(client, staff["director"])
    margin = next(i for i in route["checklist"] if i["code"] == "margin")
    assert (margin["ok"], margin["value"]) == (False, "17.6 % < 20 %")
    assert route["allowed_decisions"] == ["return", "reject"]

    blocked = await client.post(
        f"/api/v1/approvals/{route['id']}/decision", json={"decision": "approve"}, headers=staff["director"].headers
    )
    body = assert_error(blocked, 409, "CONFLICT", reason="checklist_not_green")
    assert body["details"]["failed"] == ["margin"]
    assert await outbox(container, "approval.decided") == []
    after = await only_route(client, staff["director"])
    assert after["status"] == "open" and after["outgoing_number"] is None


async def test_missing_visa_blocks_approval_and_missed_due_date_is_only_a_warning(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    visas = [
        {"zone": "goods", "by": {"crm_user_id": 11, "full_name": "Сардор Снабженцев"}, "at": "2026-10-28T07:40:00Z"}
    ]
    await ready(client, container, visas=visas, due="2026-10-27")  # ready_at 28.10 > срок 27.10, нет визы гл. инженера
    route = await only_route(client, staff["director"])
    assert {i["code"]: (i["ok"], i["blocking"]) for i in route["checklist"]} == {
        "visa_goods": (True, True),
        "visa_services": (False, True),
        "margin": (True, True),
        "due": (False, False),
    }
    assert route["allowed_decisions"] == ["return", "reject"]
    blocked = await client.post(
        f"/api/v1/approvals/{route['id']}/decision", json={"decision": "approve"}, headers=staff["director"].headers
    )
    body = assert_error(blocked, 409, "CONFLICT", reason="checklist_not_green")
    assert body["details"]["failed"] == ["visa_services"]  # «срок» — предупреждение, в отказ не входит (C1-G-1)


async def journal_of(container: Container, route_id: str) -> list[tuple[str, str | None]]:
    async with container.session_factory() as session:
        rows = await session.execute(
            text("SELECT action, comment FROM journal WHERE approval_id = :id ORDER BY id"), {"id": route_id}
        )
        return [(r.action, r.comment) for r in rows]


async def test_late_quote_is_approved_with_the_late_mark_in_route_journal_and_event(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    """C1-G-1 (решение архитектора 2026-10-26): КП готово позже срока — директор одобряет, приняв опоздание."""
    await ready(client, container, due="2026-10-27")  # визы и маржа зелёные, готово 28.10 > срок 27.10
    route = await only_route(client, staff["director"])
    due = next(i for i in route["checklist"] if i["code"] == "due")
    assert (due["ok"], due["blocking"], due["value"]) == (False, False, "готово 28.10.2026, срок 27.10.2026")
    assert route["allowed_decisions"] == ["approve", "return", "reject"] and route["approved_late"] is False

    approved = await client.post(
        f"/api/v1/approvals/{route['id']}/decision",
        json={"decision": "approve", "channels": ["cabinet"]},
        headers=staff["director"].headers,
    )
    assert approved.status_code == 200, approved.text
    body = approved.json()
    validate("Approval", body)
    assert (body["status"], body["outgoing_number"], body["approved_late"]) == ("approved", "ИСХ-001/26", True)
    assert await journal_of(container, route["id"]) == [
        ("approval.requested", None),
        ("approval.decided", None),
        ("approval.approved_late", "Одобрено с опозданием: готово 28.10.2026, срок 27.10.2026"),
    ]
    [decided] = await outbox(container, "approval.decided")
    assert decided["data"]["approved_late"] is True and decided["data"]["outgoing_number"] == "ИСХ-001/26"


async def test_quote_in_time_has_no_late_mark(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    await ready(client, container)  # срок 29.10, готово 28.10
    route = await only_route(client, staff["director"])
    approved = await client.post(
        f"/api/v1/approvals/{route['id']}/decision", json={"decision": "approve"}, headers=staff["director"].headers
    )
    assert approved.json()["approved_late"] is False
    assert [a for a, _ in await journal_of(container, route["id"])] == ["approval.requested", "approval.decided"]
    [decided] = await outbox(container, "approval.decided")
    assert "approved_late" not in decided["data"]


async def test_no_threshold_means_no_margin_restriction(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    await resolve_letter(client, staff, None)
    await ready(client, container, margin_pct="-3.5", min_margin_pct=None)
    route = await only_route(client, staff["director"])
    margin = next(i for i in route["checklist"] if i["code"] == "margin")
    assert (margin["ok"], margin["value"]) == (True, "-3.5 % (порог не задан)")


async def test_return_sends_comment_and_new_version_opens_new_round(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    await ready(client, container, version=1)
    first = await only_route(client, staff["director"])
    assert_error(
        await client.post(
            f"/api/v1/approvals/{first['id']}/decision", json={"decision": "return"}, headers=staff["director"].headers
        ),
        422,
        "VALIDATION_FAILED",
    )
    returned = await client.post(
        f"/api/v1/approvals/{first['id']}/decision",
        json={"decision": "return", "comment": "Пересчитать доставку"},
        headers=staff["director"].headers,
    )
    assert returned.status_code == 200 and returned.json()["status"] == "returned"
    [decided] = await outbox(container, "approval.decided")
    assert (decided["data"]["decision"], decided["data"]["comment"], decided["data"]["route_status"]) == (
        "return",
        "Пересчитать доставку",
        "returned",
    )
    assert decided["data"]["outgoing_number"] is None and "channels" not in decided["data"]

    await ready(client, container, version=2)
    second = await only_route(client, staff["director"])
    assert (second["round"], second["object"]["quote_version"], second["status"]) == (2, 2, "open")
    # событие о более старой версии позже новой маршрут не открывает
    await ready(client, container, version=1)
    queue = (await client.get("/api/v1/approvals", params={"mine": 0}, headers=staff["director"].headers)).json()
    assert len(queue["items"]) == 2


async def test_quote_snapshot_is_hidden_from_non_deciders(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    await ready(client, container)
    seen = await only_route(client, staff["director"])
    # менеджер с registry.read видит маршрут в реестре, но не себестоимость и маржу
    detail = await client.get(f"/api/v1/approvals/{seen['id']}", headers=staff["manager"].headers)
    assert detail.status_code == 200
    body = detail.json()
    validate("Approval", body)
    assert body["quote"] is None and body["can_decide"] is False and body["allowed_decisions"] == []
    assert next(i for i in body["checklist"] if i["code"] == "margin")["value"] is None
    assert "103000000.00" not in detail.text
    # без registry.read и не участник — маршрута «нет»
    assert_error(await client.get(f"/api/v1/approvals/{seen['id']}", headers=staff["admin"].headers), 404, "NOT_FOUND")
    decision = await client.post(
        f"/api/v1/approvals/{seen['id']}/decision", json={"decision": "approve"}, headers=staff["manager"].headers
    )
    assert decision.status_code == 403  # у менеджера нет ни одного права на решение


async def test_outgoing_numbers_of_approved_quotes_are_sequential(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    await ready(client, container, erp_quote_id=1, number="КП-2026/001", version=1)
    await ready(client, container, erp_quote_id=2, number="КП-2026/002", version=1)
    queue = (await client.get("/api/v1/approvals", headers=staff["director"].headers)).json()
    numbers = []
    for item in reversed(queue["items"]):
        done = await client.post(
            f"/api/v1/approvals/{item['id']}/decision", json={"decision": "approve"}, headers=staff["director"].headers
        )
        numbers.append(done.json()["outgoing_number"])
    assert numbers == ["ИСХ-001/26", "ИСХ-002/26"]
