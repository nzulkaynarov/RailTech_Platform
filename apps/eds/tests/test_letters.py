"""Входящие письма и резолюции (pg): регистрация, резолюция, возврат, отказ, повторная подача, события и журнал."""

from datetime import UTC, date, datetime
from typing import Any

import httpx
import pytest

from app.container import Container
from tests.conftest import FakeClock
from tests.domain import Person, outbox, validate
from tests.helpers import seed_employee, signed, user_event
from tests.test_api_auth import assert_error

pytestmark = pytest.mark.pg

NEW_LETTER: dict[str, Any] = {
    "subject": "Запрос на поставку стрелочных переводов",
    "summary": "Просим выставить коммерческое предложение на 12 комплектов.",
    "sender": {"name": "ООО «Пример Логистик»", "inn": "123456789"},
    "sender_ref": {"number": "17/к", "date": "2026-10-20"},
    "received_at": "2026-10-25",
    "urgent": True,
    "links": {"erp_request_id": 77, "erp_deal_id": 905, "deal_number": "ЗВ-2026-104", "crm_client_id": 42},
}
RESOLUTION: dict[str, Any] = {
    "text": "Рассчитать до пятницы, маржа не ниже 15 %.",
    "assignees": [{"crm_user_id": 11, "zone": "goods"}, {"crm_user_id": 12, "zone": "services"}],
    "due": "2026-10-30",
    "min_margin_pct": "15",
}


async def register(client: httpx.AsyncClient, who: Person, **changes: Any) -> dict[str, Any]:
    response = await client.post("/api/v1/letters", json={**NEW_LETTER, **changes}, headers=who.headers)
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    validate("Letter", body)
    return body


async def act(client: httpx.AsyncClient, who: Person, letter_id: str, op: str, body: Any = None) -> httpx.Response:
    return await client.post(f"/api/v1/letters/{letter_id}/{op}", json=body, headers=who.headers)


async def test_register_gives_number_status_event_and_journal(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    letter = await register(client, staff["registrar"])
    assert letter["number"] == "ВХ-001/26"
    assert letter["status"] == "awaiting_resolution"
    assert letter["registered_by"] == {"crm_user_id": 4, "full_name": "Регина Регистраторова"}
    assert letter["addressee"]["crm_user_id"] == 3  # директор по умолчанию
    assert letter["links"]["erp_deal_id"] == 905
    assert [e["action"] for e in letter["journal"]] == ["letter.registered"]

    [event] = await outbox(container, "letter.registered")
    assert event["subject"] == "ВХ-001/26"
    body = event["data"]
    assert body["letter"]["eds_letter_id"] == letter["id"]
    assert body["letter"]["sender"] == {"name": "ООО «Пример Логистик»", "inn": "123456789"}
    assert body["links"]["erp_request_id"] == 77
    assert body["actor"] == {"type": "staff", "crm_user_id": 4}

    second = await register(client, staff["registrar"], links={})
    assert second["number"] == "ВХ-002/26"


async def test_register_requires_sender_or_client(client: httpx.AsyncClient, staff: dict[str, Person]) -> None:
    response = await client.post(
        "/api/v1/letters",
        json={**NEW_LETTER, "sender": {"name": None}, "links": {"erp_deal_id": 905}},
        headers=staff["registrar"].headers,
    )
    assert_error(response, 422, "VALIDATION_FAILED")
    ok = await client.post(
        "/api/v1/letters",
        json={**NEW_LETTER, "sender": {"name": None}, "links": {"crm_client_id": 42}},
        headers=staff["registrar"].headers,
    )
    assert ok.status_code == 201
    assert ok.json()["sender"] == {"name": None, "inn": None, "contact": None}
    with_contact = await client.post(
        "/api/v1/letters",
        json={**NEW_LETTER, "sender": {"name": "ООО «Другое»", "contact": "Бахтиёр Каримов"}, "links": {}},
        headers=staff["registrar"].headers,
    )
    assert with_contact.status_code == 201, with_contact.text
    assert with_contact.json()["sender"] == {"name": "ООО «Другое»", "inn": None, "contact": "Бахтиёр Каримов"}


async def test_register_rejects_unknown_fields_and_inactive_manager(
    client: httpx.AsyncClient, staff: dict[str, Person]
) -> None:
    bad = await client.post("/api/v1/letters", json={**NEW_LETTER, "oops": 1}, headers=staff["registrar"].headers)
    assert_error(bad, 422, "VALIDATION_FAILED")
    ghost = await client.post(
        "/api/v1/letters", json={**NEW_LETTER, "manager_crm_user_id": 999}, headers=staff["registrar"].headers
    )
    assert_error(ghost, 422, "VALIDATION_FAILED")


async def test_duplicate_manual_registration_for_same_request_is_conflict(
    client: httpx.AsyncClient, staff: dict[str, Person]
) -> None:
    await register(client, staff["registrar"])
    again = await client.post("/api/v1/letters", json=NEW_LETTER, headers=staff["registrar"].headers)
    assert_error(again, 409, "CONFLICT", reason="letter_exists_for_request")


async def test_resolution_publishes_assignees_due_margin_and_links(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    letter = await register(client, staff["registrar"])
    response = await act(client, staff["director"], letter["id"], "resolution", RESOLUTION)
    assert response.status_code == 200, response.text
    body = response.json()
    validate("Letter", body)
    assert body["status"] == "resolved"
    assert body["resolution"]["min_margin_pct"] == "15"
    assert body["resolution"]["decided_by"]["crm_user_id"] == 3
    assert [a["full_name"] for a in body["resolution"]["assignees"]] == ["Сардор Снабженцев", "Ильдар Инженеров"]
    assert body["journal"][-1]["action"] == "letter.resolved"

    [event] = await outbox(container, "letter.resolved")
    resolution = event["data"]["resolution"]
    assert resolution["assignees"] == [{"crm_user_id": 11, "zone": "goods"}, {"crm_user_id": 12, "zone": "services"}]
    assert (resolution["due"], resolution["min_margin_pct"]) == ("2026-10-30", "15")
    assert event["data"]["links"] == {
        "erp_request_id": 77,
        "erp_deal_id": 905,
        "deal_number": "ЗВ-2026-104",
        "crm_client_id": 42,
        "erp_company_id": None,
    }


async def test_resolution_without_margin_and_with_fractional_margin(
    client: httpx.AsyncClient, staff: dict[str, Person]
) -> None:
    a = await register(client, staff["registrar"], links={})
    r1 = await act(client, staff["director"], a["id"], "resolution", {**RESOLUTION, "min_margin_pct": None})
    assert r1.json()["resolution"]["min_margin_pct"] is None
    b = await register(client, staff["registrar"], links={})
    r2 = await act(client, staff["director"], b["id"], "resolution", {**RESOLUTION, "min_margin_pct": "12.50"})
    assert r2.json()["resolution"]["min_margin_pct"] == "12.5"


@pytest.mark.parametrize(
    "assignees",
    [
        [{"crm_user_id": 999, "zone": "goods"}],  # нет в проекции
        [{"crm_user_id": 11, "zone": "goods"}, {"crm_user_id": 11, "zone": "goods"}],  # дубль
        [],
    ],
)
async def test_resolution_assignees_must_be_active_unique_employees(
    client: httpx.AsyncClient, staff: dict[str, Person], assignees: list[dict[str, Any]]
) -> None:
    letter = await register(client, staff["registrar"])
    response = await act(client, staff["director"], letter["id"], "resolution", {**RESOLUTION, "assignees": assignees})
    assert_error(response, 422, "VALIDATION_FAILED")


async def _resolve_with(
    client: httpx.AsyncClient, staff: dict[str, Person], assignees: list[dict[str, Any]]
) -> tuple[dict[str, Any], httpx.Response]:
    letter = await register(client, staff["registrar"], links={})
    response = await act(client, staff["director"], letter["id"], "resolution", {**RESOLUTION, "assignees": assignees})
    return letter, response


@pytest.mark.parametrize(
    "assignees",
    [
        [{"crm_user_id": 11, "zone": "services"}],  # снабженец — не зона «услуги»
        [{"crm_user_id": 12, "zone": "goods"}],  # инженер — не зона «товары»
        [{"crm_user_id": 11, "zone": "payment_terms"}],  # снабженец — не условия оплаты
        [{"crm_user_id": 11, "zone": "goods"}, {"crm_user_id": 6, "zone": "goods"}],  # бухгалтер — не товары
        [{"crm_user_id": 5, "zone": "goods"}],  # менеджер: разделов расчёта нет вовсе
    ],
)
async def test_resolution_assignee_must_hold_the_section_of_the_zone(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person], assignees: list[dict[str, Any]]
) -> None:
    """B-007: исполнитель зоны — держатель её раздела каталога; иначе 422, письмо ждёт резолюции, события нет."""
    letter, response = await _resolve_with(client, staff, assignees)

    body = assert_error(response, 422, "VALIDATION_FAILED")
    assert body["details"]["fields"] == [
        {"field": "assignees", "message": "assignee_zone_mismatch", "type": "value_error"}
    ]
    assert await outbox(container, "letter.resolved") == []
    card = (await client.get(f"/api/v1/letters/{letter['id']}", headers=staff["director"].headers)).json()
    assert card["status"] == "awaiting_resolution"


async def test_resolution_accepts_every_zone_of_its_holder_and_the_universal_role(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    pairs = [
        {"crm_user_id": 11, "zone": "goods"},
        {"crm_user_id": 12, "zone": "services"},
        {"crm_user_id": 6, "zone": "payment_terms"},
        {"crm_user_id": 3, "zone": "goods"},  # директор по каталогу держит все три раздела зон
        {"crm_user_id": 3, "zone": "services"},
        {"crm_user_id": 3, "zone": "payment_terms"},
    ]
    _, response = await _resolve_with(client, staff, pairs)

    assert response.status_code == 200, response.text
    [event] = await outbox(container, "letter.resolved")
    assert len(event["data"]["resolution"]["assignees"]) == 6


async def test_resolution_zone_needs_full_level_and_a_projection_with_sections(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    """Уровень `read` раздела зоны не делает исполнителем; проекция без разделов (снимок до D1-8) — тоже."""
    await seed_employee(
        container, 11, full_name="Сардор Снабженцев", permissions={"eds": [], "sections": {"erp.calc.goods": "read"}}
    )
    _, read_only = await _resolve_with(client, staff, [{"crm_user_id": 11, "zone": "goods"}])
    assert_error(read_only, 422, "VALIDATION_FAILED")

    await seed_employee(container, 11, full_name="Сардор Снабженцев", permissions={"eds": ["registry.read"]})
    _, old_snapshot = await _resolve_with(client, staff, [{"crm_user_id": 11, "zone": "goods"}])
    assert_error(old_snapshot, 422, "VALIDATION_FAILED")

    await seed_employee(
        container, 11, full_name="Сардор Снабженцев", permissions={"eds": [], "sections": {"erp.calc.goods": "full"}}
    )
    _, full = await _resolve_with(client, staff, [{"crm_user_id": 11, "zone": "goods"}])
    assert full.status_code == 200, full.text


async def test_after_a_deploy_the_republished_snapshot_restores_the_zone(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    """Выкладка D1-8: проекция без разделов (старый снимок) -> 422; CRM по новому отпечатку каталога
    переопубликует `identity.user.updated` с `permissions.sections` -> резолюция проходит."""
    old = {"eds": ["registry.read"]}
    await seed_employee(container, 11, full_name="Сардор Снабженцев", permissions=old)
    pair = [{"crm_user_id": 11, "zone": "goods"}]
    _, before = await _resolve_with(client, staff, pair)
    assert_error(before, 422, "VALIDATION_FAILED")

    republished = user_event(
        "updated",
        crm_user_id=11,
        full_name="Сардор Снабженцев",
        permissions={"eds": ["registry.read"], "sections": {"erp.calc": "full", "erp.calc.goods": "full"}},
    )
    headers, body = signed(republished)
    assert (await client.post("/bus/v1/events", headers=headers, content=body)).status_code == 200
    assert await container.bus.process_inbox(republished["id"]) == "processed"

    _, after = await _resolve_with(client, staff, pair)
    assert after.status_code == 200, after.text


async def test_resolution_due_in_the_past_is_rejected_today_is_accepted(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person], clock: FakeClock
) -> None:
    """C1-G-1 (решение архитектора 2026-10-26): срок резолюции раньше сегодняшней даты по Asia/Tashkent — 422."""
    letter = await register(client, staff["registrar"])
    past = await act(client, staff["director"], letter["id"], "resolution", {**RESOLUTION, "due": "2026-10-25"})
    body = assert_error(past, 422, "VALIDATION_FAILED")
    assert [f["field"] for f in body["details"]["fields"]] == ["due"]
    assert await outbox(container, "letter.resolved") == []
    # 26.10 20:30 UTC — уже 27.10 в Ташкенте (UTC+5): «вчера» по часовому поясу компании — 26.10
    clock.set(datetime(2026, 10, 26, 20, 30, tzinfo=UTC))
    still_past = await act(client, staff["director"], letter["id"], "resolution", {**RESOLUTION, "due": "2026-10-26"})
    assert_error(still_past, 422, "VALIDATION_FAILED")
    today = await act(client, staff["director"], letter["id"], "resolution", {**RESOLUTION, "due": "2026-10-27"})
    assert today.status_code == 200, today.text
    assert today.json()["resolution"]["due"] == "2026-10-27"


async def test_return_requires_comment_and_resubmit_keeps_the_number(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    letter = await register(client, staff["registrar"])
    for payload in ({}, {"comment": ""}, {"comment": None}):
        assert_error(await act(client, staff["director"], letter["id"], "return", payload), 422, "VALIDATION_FAILED")

    returned = await act(client, staff["director"], letter["id"], "return", {"comment": "Уточните количество"})
    assert returned.status_code == 200
    assert returned.json()["status"] == "returned"
    assert returned.json()["return_comment"] == "Уточните количество"
    [event] = await outbox(container, "letter.returned")
    assert event["data"]["comment"] == "Уточните количество"

    # из «возвращено» нельзя ни наложить резолюцию, ни вернуть, ни отклонить
    for op, body in (("resolution", RESOLUTION), ("return", {"comment": "ещё"}), ("reject", {"reason": "нет"})):
        assert_error(
            await act(client, staff["director"], letter["id"], op, body), 409, "CONFLICT", reason="invalid_state"
        )

    resubmitted = await act(
        client, staff["registrar"], letter["id"], "submit", {"subject": "Запрос (уточнён)", "comment": "12 → 14"}
    )
    assert resubmitted.status_code == 200, resubmitted.text
    body = resubmitted.json()
    validate("Letter", body)
    assert (body["status"], body["number"], body["subject"]) == (
        "awaiting_resolution",
        letter["number"],
        "Запрос (уточнён)",
    )
    assert body["return_comment"] is None
    assert [e["action"] for e in body["journal"]] == ["letter.registered", "letter.returned", "letter.resubmitted"]
    assert body["journal"][-1]["comment"] == "12 → 14"
    assert len(await outbox(container, "letter.registered")) == 1  # повторная подача событий не публикует
    assert (await act(client, staff["director"], letter["id"], "resolution", RESOLUTION)).status_code == 200


async def test_resubmit_without_body_and_only_from_returned(
    client: httpx.AsyncClient, staff: dict[str, Person]
) -> None:
    letter = await register(client, staff["registrar"])
    assert_error(await act(client, staff["registrar"], letter["id"], "submit"), 409, "CONFLICT", reason="invalid_state")
    await act(client, staff["director"], letter["id"], "return", {"comment": "Правки"})
    assert (await act(client, staff["registrar"], letter["id"], "submit")).status_code == 200


async def test_reject_requires_reason_and_is_final(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    letter = await register(client, staff["registrar"])
    assert_error(await act(client, staff["director"], letter["id"], "reject", {"reason": ""}), 422, "VALIDATION_FAILED")
    rejected = await act(client, staff["director"], letter["id"], "reject", {"reason": "Не наш профиль"})
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"
    assert rejected.json()["reject_reason"] == "Не наш профиль"
    [event] = await outbox(container, "letter.rejected")
    assert event["data"]["reason"] == "Не наш профиль"
    assert event["data"]["links"]["erp_deal_id"] == 905
    for op, body in (("resolution", RESOLUTION), ("return", {"comment": "x"}), ("reject", {"reason": "y"})):
        assert_error(
            await act(client, staff["director"], letter["id"], op, body), 409, "CONFLICT", reason="invalid_state"
        )
    assert_error(await act(client, staff["registrar"], letter["id"], "submit"), 409, "CONFLICT", reason="invalid_state")


async def test_unknown_letter_is_404(client: httpx.AsyncClient, staff: dict[str, Person]) -> None:
    ghost = "00000000-0000-4000-8000-000000000000"
    assert_error(await client.get(f"/api/v1/letters/{ghost}", headers=staff["director"].headers), 404, "NOT_FOUND")
    assert_error(await act(client, staff["director"], ghost, "reject", {"reason": "x"}), 404, "NOT_FOUND")


async def test_list_filters_search_and_cursor_pagination(client: httpx.AsyncClient, staff: dict[str, Person]) -> None:
    made = [
        await register(client, staff["registrar"], subject=f"Письмо {n}", links={"deal_number": f"ЗВ-2026-{n:03d}"})
        for n in range(1, 6)
    ]
    await act(client, staff["director"], made[0]["id"], "reject", {"reason": "нет"})
    headers = staff["manager"].headers

    first = await client.get("/api/v1/letters", params={"limit": 2}, headers=headers)
    page = first.json()
    validate("LetterPage", page)
    assert [i["subject"] for i in page["items"]] == ["Письмо 5", "Письмо 4"]  # от новых к старым
    second = (
        await client.get("/api/v1/letters", params={"limit": 2, "cursor": page["next_cursor"]}, headers=headers)
    ).json()
    assert [i["subject"] for i in second["items"]] == ["Письмо 3", "Письмо 2"]
    last = (
        await client.get("/api/v1/letters", params={"limit": 2, "cursor": second["next_cursor"]}, headers=headers)
    ).json()
    assert [i["subject"] for i in last["items"]] == ["Письмо 1"]
    assert last["next_cursor"] is None

    rejected = (await client.get("/api/v1/letters", params={"status": "rejected"}, headers=headers)).json()
    assert [i["subject"] for i in rejected["items"]] == ["Письмо 1"]
    both = (
        await client.get("/api/v1/letters", params=[("status", "rejected"), ("status", "returned")], headers=headers)
    ).json()
    assert len(both["items"]) == 1
    by_deal = (await client.get("/api/v1/letters", params={"q": "ЗВ-2026-003"}, headers=headers)).json()
    assert [i["subject"] for i in by_deal["items"]] == ["Письмо 3"]
    by_number = (await client.get("/api/v1/letters", params={"q": "ВХ-004"}, headers=headers)).json()
    assert [i["subject"] for i in by_number["items"]] == ["Письмо 4"]
    assert (await client.get("/api/v1/letters", params={"q": "100%"}, headers=headers)).json()["items"] == []

    bad = await client.get("/api/v1/letters", params={"cursor": "не-курсор"}, headers=headers)
    assert_error(bad, 422, "VALIDATION_FAILED")


async def test_letter_due_shows_in_list_after_resolution(client: httpx.AsyncClient, staff: dict[str, Person]) -> None:
    letter = await register(client, staff["registrar"])
    await act(client, staff["director"], letter["id"], "resolution", RESOLUTION)
    items = (await client.get("/api/v1/letters", headers=staff["manager"].headers)).json()["items"]
    assert items[0]["due"] == date(2026, 10, 30).isoformat()


async def test_idempotency_key_replays_same_response_and_rejects_other_body(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    headers = {**staff["registrar"].headers, "Idempotency-Key": "key-0001-letter"}
    first = await client.post("/api/v1/letters", json=NEW_LETTER, headers=headers)
    again = await client.post("/api/v1/letters", json=NEW_LETTER, headers=headers)
    assert (first.status_code, again.status_code) == (201, 201)
    assert first.json() == again.json()
    assert len(await outbox(container, "letter.registered")) == 1

    other = await client.post("/api/v1/letters", json={**NEW_LETTER, "subject": "Другое"}, headers=headers)
    assert_error(other, 409, "CONFLICT", reason="idempotency_key_reused")
    # тот же ключ у другого сотрудника — отдельная запись
    director = {**staff["director"].headers, "Idempotency-Key": "key-0001-letter"}
    assert (await client.post("/api/v1/letters", json={**NEW_LETTER, "links": {}}, headers=director)).status_code == 201


async def test_resubmit_cannot_take_over_another_letters_request(
    client: httpx.AsyncClient, staff: dict[str, Person]
) -> None:
    await register(client, staff["registrar"])  # заявка 77
    other = await register(client, staff["registrar"], links={"erp_request_id": 78})
    await act(client, staff["director"], other["id"], "return", {"comment": "Правки"})
    clash = await act(client, staff["registrar"], other["id"], "submit", {"links": {"erp_request_id": 77}})
    assert_error(clash, 409, "CONFLICT", reason="letter_exists_for_request")
    ok = await act(
        client, staff["registrar"], other["id"], "submit", {"links": {"erp_deal_id": 910, "erp_request_id": 78}}
    )
    assert ok.status_code == 200 and ok.json()["links"]["erp_deal_id"] == 910
