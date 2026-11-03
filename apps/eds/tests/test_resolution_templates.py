"""Шаблоны резолюций (EDS-REG, R2, pg): личные у директора и делопроизводителя, общие у администратора, видимость,
правила «Для сведения», активные сотрудники, журнал; названия видов резолюции — закрытый справочник."""

from typing import Any

import httpx
import pytest
from sqlalchemy import select

from app.container import Container
from app.models import JournalEntry
from tests.domain import Person, validate
from tests.test_api_auth import assert_error

pytestmark = pytest.mark.pg

BASE = "/api/v1/resolution-templates"
REPLY: dict[str, Any] = {
    "name": "Налоговая — ответ бухгалтерии",
    "scope": "personal",
    "kind": "reply",
    "text": "Подготовить ответ и согласовать со мной.",
    "responsible_type": "person",
    "responsible_crm_user_id": 6,
    "co_executor_ids": [5],
    "acquaint_ids": [4],
    "due_days": 5,
}


async def save(client: httpx.AsyncClient, who: Person, **body: Any) -> httpx.Response:
    return await client.post(BASE, json={**REPLY, **body}, headers=who.headers)


async def listed(client: httpx.AsyncClient, who: Person) -> list[dict[str, Any]]:
    response = await client.get(BASE, headers=who.headers)
    assert response.status_code == 200, response.text
    validate("ResolutionTemplateList", response.json())
    items: list[dict[str, Any]] = response.json()["items"]
    return items


async def test_director_saves_a_personal_template_others_do_not_see_it(
    client: httpx.AsyncClient, staff: dict[str, Person], container: Container
) -> None:
    created = await save(client, staff["director"])
    assert created.status_code == 201, created.text
    body = created.json()
    validate("ResolutionTemplate", body)
    assert (body["scope"], body["kind"], body["due_days"], body["editable"]) == ("personal", "reply", 5, True)
    assert body["responsible"] == {"crm_user_id": 6, "full_name": "Бахтиёр Бухгалтеров"}
    assert [p["crm_user_id"] for p in body["co_executors"]] == [5]
    assert body["owner"]["crm_user_id"] == 3

    assert [t["name"] for t in await listed(client, staff["director"])] == [REPLY["name"]]
    assert await listed(client, staff["registrar"]) == []  # чужой личный не виден
    other = await client.put(f"{BASE}/{body['id']}", json=REPLY, headers=staff["registrar"].headers)
    assert_error(other, 404, "NOT_FOUND")
    assert_error(await client.delete(f"{BASE}/{body['id']}", headers=staff["registrar"].headers), 404, "NOT_FOUND")

    async with container.session_factory() as session:
        actions = (await session.execute(select(JournalEntry.action, JournalEntry.by_crm_user_id))).all()
    assert ("resolution_template.created", 3) in actions


async def test_company_template_is_admins_and_visible_to_all_authors(
    client: httpx.AsyncClient, staff: dict[str, Person]
) -> None:
    denied = await save(client, staff["director"], scope="company", name="Общий")
    assert_error(denied, 403, "FORBIDDEN", reason="company_template_admin_only")
    created = await save(client, staff["admin"], scope="company", name="Банк — к сведению", kind="info")
    assert created.status_code == 201, created.text
    shared = created.json()
    # «Для сведения»: ответственного, соисполнителей и срока нет — код их снимает.
    assert (shared["responsible_type"], shared["responsible"], shared["co_executors"], shared["due_days"]) == (
        "none",
        None,
        [],
        None,
    )
    assert [p["crm_user_id"] for p in shared["acquaint"]] == [4]
    assert shared["owner"] is None

    mine = (await save(client, staff["director"])).json()
    seen = await listed(client, staff["director"])
    assert [t["id"] for t in seen] == [mine["id"], shared["id"]]  # сначала свои, потом общие
    assert [t["editable"] for t in seen] == [True, False]
    assert [t["name"] for t in await listed(client, staff["registrar"])] == ["Банк — к сведению"]

    edit = await client.put(
        f"{BASE}/{shared['id']}", json={**REPLY, "scope": "company"}, headers=staff["director"].headers
    )
    assert_error(edit, 403, "FORBIDDEN", reason="company_template_admin_only")
    renamed = await client.put(
        f"{BASE}/{shared['id']}",
        json={**REPLY, "scope": "company", "name": "Банк — ответ", "responsible_type": "addressee"},
        headers=staff["admin"].headers,
    )
    assert renamed.status_code == 200, renamed.text
    assert (renamed.json()["name"], renamed.json()["responsible_type"], renamed.json()["responsible"]) == (
        "Банк — ответ",
        "addressee",
        None,
    )
    scope = await client.put(f"{BASE}/{shared['id']}", json=REPLY, headers=staff["admin"].headers)
    assert_error(scope, 422, "VALIDATION_FAILED")
    removed = await client.delete(f"{BASE}/{shared['id']}", headers=staff["admin"].headers)
    assert removed.status_code == 204
    assert [t["id"] for t in await listed(client, staff["director"])] == [mine["id"]]


async def test_template_rules(client: httpx.AsyncClient, staff: dict[str, Person]) -> None:
    director = staff["director"]
    assert (await save(client, director)).status_code == 201
    again = await save(client, director, name=" налоговая — ОТВЕТ бухгалтерии ")
    assert_error(again, 409, "CONFLICT", reason="name_taken")
    # Тот же текст у другого владельца — не конфликт.
    assert (await save(client, staff["registrar"])).status_code == 201

    nobody = await save(client, director, name="Неактивный", responsible_crm_user_id=999, acquaint_ids=[998])
    assert_error(nobody, 422, "VALIDATION_FAILED")
    fields = {f["field"]: f["message"] for f in nobody.json()["details"]["fields"]}
    assert fields == {"responsible_crm_user_id": "not_active_employee", "acquaint_ids": "not_active_employee"}
    missing = await save(client, director, name="Без ответственного", responsible_crm_user_id=None)
    assert_error(missing, 422, "VALIDATION_FAILED")
    free = await save(client, director, name="Выбрать при резолюции", responsible_type="none", due_days=None)
    assert free.status_code == 201, free.text
    assert free.json()["responsible"] is None
    assert_error(await save(client, director, name="Долгий", due_days=400), 422, "VALIDATION_FAILED")


async def test_who_may_use_templates(client: httpx.AsyncClient, staff: dict[str, Person]) -> None:
    for who in ("manager", "supplier"):
        assert_error(await client.get(BASE, headers=staff[who].headers), 403, "FORBIDDEN")
    personal = await save(client, staff["admin"], name="Свой у администратора")
    assert_error(personal, 403, "FORBIDDEN", reason="personal_template_not_allowed")
    # Администратору для людей общих шаблонов открыт список сотрудников.
    assert (await client.get("/api/v1/employees", headers=staff["admin"].headers)).status_code == 200


async def test_resolution_kind_names_are_a_closed_dictionary(
    client: httpx.AsyncClient, staff: dict[str, Person]
) -> None:
    base = "/api/v1/dictionaries/resolution-kinds"
    items = (await client.get(base, headers=staff["director"].headers)).json()["items"]
    assert [(i["code"], i["name"]["ru"]) for i in items] == [
        ("execute", "К исполнению"),
        ("reply", "Подготовить ответ"),
        ("info", "Для сведения"),
    ]
    admin = staff["admin"].headers
    added = await client.post(base, json={"name": {"ru": "На подпись"}}, headers=admin)
    assert_error(added, 409, "CONFLICT", reason="dictionary_closed")
    hidden = await client.patch(f"{base}/info", json={"active": False}, headers=admin)
    assert_error(hidden, 409, "CONFLICT", reason="dictionary_closed")
    assert_error(await client.delete(f"{base}/info", headers=admin), 409, "CONFLICT", reason="dictionary_closed")
    renamed = await client.patch(
        f"{base}/info", json={"name": {"ru": "Ознакомиться", "uz": "", "en": ""}}, headers=admin
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["code"] == "info"
    ordered = await client.put(f"{base}/order", json={"codes": ["reply", "execute", "info"]}, headers=admin)
    assert ordered.status_code == 200, ordered.text
    catalog = (await client.get("/api/v1/dictionaries", headers=admin)).json()["items"]
    assert {d["kind"]: d["closed"] for d in catalog}["resolution-kinds"] is True
