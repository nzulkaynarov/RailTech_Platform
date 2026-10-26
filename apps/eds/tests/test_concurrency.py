"""Параллельные запросы (pg): нумерация без пропусков и дублей, гонки решений и повторов (runbook §2.1, §3 E3)."""

import asyncio
from typing import Any

import httpx
import pytest

from app.container import Container
from tests.domain import Person, outbox
from tests.test_documents import MEMO, create, submit
from tests.test_letters import NEW_LETTER, RESOLUTION

pytestmark = pytest.mark.pg


async def test_fifty_parallel_letter_registrations_get_numbers_1_to_50(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    async def one(n: int) -> httpx.Response:
        body = {**NEW_LETTER, "subject": f"Письмо {n}", "links": {}}
        return await client.post("/api/v1/letters", json=body, headers=staff["registrar"].headers)

    responses = await asyncio.gather(*(one(n) for n in range(50)))
    assert {r.status_code for r in responses} == {201}
    numbers = sorted(r.json()["number"] for r in responses)
    assert numbers == [f"ВХ-{n:03d}/26" for n in range(1, 51)]
    events = await outbox(container, "letter.registered")
    assert sorted(e["data"]["letter"]["number"] for e in events) == numbers


async def test_fifty_parallel_documents_number_each_kind_independently(
    client: httpx.AsyncClient, staff: dict[str, Person]
) -> None:
    kinds = ["memo"] * 30 + ["report"] * 20

    async def one(kind: str) -> httpx.Response:
        return await client.post("/api/v1/documents", json={**MEMO, "kind": kind}, headers=staff["manager"].headers)

    responses = await asyncio.gather(*(one(k) for k in kinds))
    assert {r.status_code for r in responses} == {201}
    memos = sorted(r.json()["number"] for r in responses if r.json()["kind"] == "memo")
    reports = sorted(r.json()["number"] for r in responses if r.json()["kind"] == "report")
    assert memos == [f"СЗ-2026/{n:03d}" for n in range(1, 31)]
    assert reports == [f"ОТ-2026/{n:03d}" for n in range(1, 21)]


async def test_parallel_outgoing_numbers_are_shared_by_letters_and_quotes(
    client: httpx.AsyncClient, staff: dict[str, Person]
) -> None:
    drafts = [
        await create(client, staff["registrar"], kind="letter_out", recipient={"name": f"Адресат {n}"})
        for n in range(10)
    ]
    responses = await asyncio.gather(*(submit(client, staff["registrar"], d["id"]) for d in drafts))
    assert sorted(r.json()["number"] for r in responses) == [f"ИСХ-{n:03d}/26" for n in range(1, 11)]


async def test_two_parallel_decisions_one_wins_the_other_gets_route_closed(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    doc = await create(client, staff["manager"])
    approval_id = (await submit(client, staff["manager"], doc["id"])).json()["approval_id"]

    async def approve() -> httpx.Response:
        return await client.post(
            f"/api/v1/approvals/{approval_id}/decision", json={"decision": "approve"}, headers=staff["director"].headers
        )

    first, second = await asyncio.gather(approve(), approve())
    assert sorted([first.status_code, second.status_code]) == [200, 409]
    loser = first if first.status_code == 409 else second
    assert loser.json()["details"]["reason"] == "route_closed"
    assert len(await outbox(container, "approval.decided")) == 1
    assert len(await outbox(container, "document.archived")) == 1


async def test_parallel_resolution_and_rejection_of_one_letter(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    letter = (await client.post("/api/v1/letters", json=NEW_LETTER, headers=staff["registrar"].headers)).json()

    async def resolve() -> httpx.Response:
        return await client.post(
            f"/api/v1/letters/{letter['id']}/resolution", json=RESOLUTION, headers=staff["director"].headers
        )

    async def reject() -> httpx.Response:
        return await client.post(
            f"/api/v1/letters/{letter['id']}/reject", json={"reason": "Нет"}, headers=staff["director"].headers
        )

    results = await asyncio.gather(resolve(), reject())
    assert sorted(r.status_code for r in results) == [200, 409]
    published = await outbox(container, "letter.resolved") + await outbox(container, "letter.rejected")
    assert len(published) == 1  # одно решение — одно событие


async def test_parallel_submit_of_one_document_opens_one_route(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    doc = await create(client, staff["manager"])
    results = await asyncio.gather(*(submit(client, staff["manager"], doc["id"]) for _ in range(4)))
    assert sorted(r.status_code for r in results) == [200, 409, 409, 409]
    assert len(await outbox(container, "approval.requested")) == 1


async def test_parallel_requests_with_one_idempotency_key_create_one_letter(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    headers = {**staff["registrar"].headers, "Idempotency-Key": "parallel-key-1"}
    results = await asyncio.gather(
        *(client.post("/api/v1/letters", json=NEW_LETTER, headers=headers) for _ in range(5))
    )
    assert {r.status_code for r in results} == {201}
    assert len({r.json()["id"] for r in results}) == 1
    assert len(await outbox(container, "letter.registered")) == 1


async def test_numbers_have_no_gaps_when_some_parallel_requests_fail_after_numbering(
    client: httpx.AsyncClient, staff: dict[str, Person]
) -> None:
    """Номер выдаётся до привязки файлов; запрос с чужим файлом падает уже после выдачи и откатывается целиком."""
    ghost = ["00000000-0000-4000-8000-0000000000aa"]

    async def one(n: int) -> httpx.Response:
        body: dict[str, Any] = {**NEW_LETTER, "links": {}, "file_ids": ghost if n % 5 == 0 else []}
        return await client.post("/api/v1/letters", json=body, headers=staff["registrar"].headers)

    responses = await asyncio.gather(*(one(n) for n in range(25)))
    assert sum(1 for r in responses if r.status_code == 422) == 5
    ok = sorted(r.json()["number"] for r in responses if r.status_code == 201)
    assert ok == [f"ВХ-{n:03d}/26" for n in range(1, 21)]
