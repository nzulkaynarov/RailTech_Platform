"""Ключи идемпотентности (pg): срок 24 часа, уборка просроченных, ключ принадлежит сотруднику и операции."""

import httpx
import pytest
from sqlalchemy import text

from app.container import Container
from app.services import idempotency
from tests.conftest import FakeClock
from tests.domain import Person
from tests.test_documents import MEMO
from tests.test_letters import NEW_LETTER

pytestmark = pytest.mark.pg


async def test_key_expires_after_24_hours_and_is_purged(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person], clock: FakeClock
) -> None:
    headers = {**staff["registrar"].headers, "Idempotency-Key": "expiring-key-1"}
    first = await client.post("/api/v1/letters", json=NEW_LETTER, headers=headers)
    clock.advance(hours=23)
    assert (await client.post("/api/v1/letters", json={**NEW_LETTER}, headers=headers)).json()["id"] == first.json()[
        "id"
    ]

    clock.advance(hours=2)  # ключу больше суток: операция выполняется заново
    second = await client.post("/api/v1/letters", json={**NEW_LETTER, "links": {}}, headers=headers)
    assert second.status_code == 201 and second.json()["id"] != first.json()["id"]

    clock.advance(hours=25)
    async with container.session_factory() as session, session.begin():
        assert await idempotency.purge_expired(session) == 1
    async with container.session_factory() as session:
        assert (await session.execute(text("SELECT count(*) FROM idempotency_keys"))).scalar_one() == 0


async def test_same_key_in_different_operations_is_independent(
    client: httpx.AsyncClient, staff: dict[str, Person]
) -> None:
    headers = {**staff["registrar"].headers, "Idempotency-Key": "shared-key-0001"}
    letter = await client.post("/api/v1/letters", json=NEW_LETTER, headers=headers)
    memo = await client.post("/api/v1/documents", json=MEMO, headers=headers)
    assert (letter.status_code, memo.status_code) == (201, 201)
    assert memo.json()["kind"] == "memo"


async def test_failed_request_does_not_burn_the_key(client: httpx.AsyncClient, staff: dict[str, Person]) -> None:
    headers = {**staff["registrar"].headers, "Idempotency-Key": "retry-after-error"}
    bad = await client.post("/api/v1/letters", json={**NEW_LETTER, "manager_crm_user_id": 999}, headers=headers)
    assert bad.status_code == 422
    good = await client.post("/api/v1/letters", json=NEW_LETTER, headers=headers)
    assert good.status_code == 201
