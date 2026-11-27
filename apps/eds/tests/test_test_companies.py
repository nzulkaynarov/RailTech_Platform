"""ТЕСТ-1 (pg): отметка «Тестовая» компании ERP — проекция из `erp.company.updated`; письма и реестр без тестовых."""

import copy
from typing import Any

import httpx
import pytest
from sqlalchemy import text

from app.container import Container
from tests.domain import Person, deliver_erp
from tests.helpers import example

pytestmark = pytest.mark.pg

COMPANY = 118  # компания из примера `erp/request.created.v1`


def company_event(at: str, **company: Any) -> dict[str, Any]:
    envelope = copy.deepcopy(example("erp/company.updated.v1"))
    envelope["data"]["erp_company_id"] = COMPANY
    envelope["data"]["company"].update({"updated_at": at, **company})
    return envelope


async def letters(client: httpx.AsyncClient, who: Person, query: str = "") -> list[dict[str, Any]]:
    response = await client.get(f"/api/v1/letters{query}", headers=who.headers)
    assert response.status_code == 200, response.text
    return list(response.json()["items"])


async def registry(client: httpx.AsyncClient, who: Person, query: str = "") -> list[dict[str, Any]]:
    response = await client.get(f"/api/v1/registry{query}", headers=who.headers)
    assert response.status_code == 200, response.text
    return list(response.json()["items"])


async def test_test_company_documents_leave_lists_and_come_back(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    assert await deliver_erp(client, container, example("erp/request.created.v1")) == "processed"
    manager = staff["manager"]
    assert len(await letters(client, manager)) == 1
    letter_id = (await letters(client, manager))[0]["id"]

    assert await deliver_erp(client, container, company_event("2026-11-27T09:00:00Z", is_test=True)) == "processed"
    assert await letters(client, manager) == []
    assert [row["id"] for row in await letters(client, manager, "?test=only")] == [letter_id]
    assert len(await letters(client, manager, "?test=all")) == 1
    assert [row for row in await registry(client, manager) if row["links"]["erp_company_id"] == COMPANY] == []
    assert (await client.get(f"/api/v1/letters/{letter_id}", headers=manager.headers)).status_code == 200  # по номеру

    # более старый снимок отметку не снимает; снимок без поля её не меняет
    assert await deliver_erp(client, container, company_event("2026-11-27T08:00:00Z", is_test=False)) == "processed"
    assert await letters(client, manager) == []
    without = company_event("2026-11-27T09:30:00Z")
    del without["data"]["company"]["is_test"]
    assert await deliver_erp(client, container, without) == "processed"
    assert await letters(client, manager) == []

    assert await deliver_erp(client, container, company_event("2026-11-27T10:00:00Z", is_test=False)) == "processed"
    assert len(await letters(client, manager)) == 1
    async with container.session_factory() as session:
        row = (
            await session.execute(text("SELECT is_test FROM company_marks WHERE erp_company_id = :c"), {"c": COMPANY})
        ).one()
    assert row.is_test is False
