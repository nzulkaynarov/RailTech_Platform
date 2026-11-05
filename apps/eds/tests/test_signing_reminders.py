"""Напоминание об окончании полномочия подписи за 14 дней (pg; SIGN-2, ADR-0024 п. 1): кому, когда, один раз, откат."""

import json
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
import jsonschema
import pytest
from referencing import Registry, Resource
from sqlalchemy import select, text

from app.container import Container
from app.models import SigningAuthority
from app.services import signing_reminders
from tests.domain import Person, outbox, validate
from tests.helpers import EVENTS, example, seed_employee

pytestmark = pytest.mark.pg

# 09:30 в Ташкенте (UTC+5) = 04:30 UTC
NOON = datetime(2026, 11, 5, 4, 30, tzinfo=UTC)
URL = "/api/v1/signing/authorities"


def poa(user: int, ends: str, number: str = "17") -> dict[str, Any]:
    return {
        "crm_user_id": user,
        "kinds": ["letter_out"],
        "basis": "power_of_attorney",
        "basis_number": number,
        "basis_date": "2026-01-10",
        "valid_from": "2026-01-10",
        "valid_to": ends,
    }


async def issue(client: httpx.AsyncClient, admin: Person, body: dict[str, Any]) -> str:
    response = await client.post(URL, json=body, headers=admin.headers)
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


async def run(container: Container, now: datetime = NOON) -> int:
    async with container.session_factory() as session, session.begin():
        return await signing_reminders.send_expiry_reminders(session, container.bus, now=now)


def test_days_word_agrees_with_the_number() -> None:
    assert [signing_reminders.days_word(n) for n in (1, 2, 5, 11, 12, 14, 21, 22, 25)] == [
        "1 день", "2 дня", "5 дней", "11 дней", "12 дней", "14 дней", "21 день", "22 дня", "25 дней",
    ]  # fmt: skip


async def test_reminder_goes_to_the_register_keepers_fourteen_days_before_the_end(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    await issue(client, staff["admin"], poa(5, "2026-11-19"))  # ровно через 14 дней
    assert await run(container) == 1
    (event,) = await outbox(container, "signing_authority.expiring")
    data = event["data"]
    assert data["recipients"] == [9]  # единственный держатель signing.manage
    assert data["authority"]["days_left"] == 14 and data["authority"]["holder"]["crm_user_id"] == 5
    assert data["title"] == "Доверенность Алия Каримова заканчивается 19.11.2026"
    assert "Осталось 14 дней" in data["subtitle"] and "Права подписи" in data["subtitle"]
    assert event["subject"].startswith("signing-authority/")
    # событие соответствует контракту (схема и пример каталога)
    import json

    from tests.helpers import EVENTS

    schema = json.loads((EVENTS / "eds" / "signing_authority.expiring.v1.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema, registry=_registry(), format_checker=jsonschema.FormatChecker()).validate(
        data
    )
    validate(
        "SigningAuthorityDetail",
        (await client.get(f"{URL}/{await _only_id(container)}", headers=staff["admin"].headers)).json(),
    )


def _registry() -> Any:
    defs = json.loads((EVENTS / "eds" / "_defs.v1.json").read_text(encoding="utf-8"))
    return Registry().with_resource(defs["$id"], Resource.from_contents(defs))


async def _only_id(container: Container) -> uuid.UUID:
    async with container.session_factory() as session:
        return (await session.execute(select(SigningAuthority.id))).scalar_one()


async def test_reminder_is_sent_once_per_end_date_and_again_after_the_term_moves(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    authority_id = await issue(client, staff["admin"], poa(5, "2026-11-12"))
    assert await run(container) == 1
    assert await run(container, NOON + timedelta(hours=3)) == 0  # повтор в тот же день
    assert await run(container, NOON + timedelta(days=1)) == 0  # и на следующий
    assert len(await outbox(container, "signing_authority.expiring")) == 1

    moved = await client.patch(f"{URL}/{authority_id}", json={"valid_to": "2026-11-18"}, headers=staff["admin"].headers)
    assert moved.status_code == 200
    assert await run(container) == 1  # срок перенесли, но он снова близко — новое напоминание на новую дату
    assert len(await outbox(container, "signing_authority.expiring")) == 2
    journal = (await client.get(f"{URL}/{authority_id}", headers=staff["admin"].headers)).json()["journal"]
    assert [e["action"] for e in journal].count("expiry_reminded") == 2


@pytest.mark.parametrize(
    "ends",
    ["2026-11-20", "2026-11-04", "2027-02-01"],  # дальше 14 дней, уже кончилось, далеко
)
async def test_no_reminder_outside_the_window(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person], ends: str
) -> None:
    body = poa(5, ends)
    if ends == "2026-11-04":
        body |= {"basis_date": "2025-12-01", "valid_from": "2025-12-01"}
    await issue(client, staff["admin"], body)
    assert await run(container) == 0
    assert await outbox(container, "signing_authority.expiring") == []


async def test_no_reminder_for_revoked_or_deactivated_holder_and_none_before_nine(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    revoked = await issue(client, staff["admin"], poa(5, "2026-11-12", "1"))
    await client.post(f"{URL}/{revoked}/revoke", json={"reason": "Отозвана"}, headers=staff["admin"].headers)
    await issue(client, staff["admin"], poa(6, "2026-11-12", "2"))
    await seed_employee(
        container, 6, full_name="Бахтиёр Бухгалтеров", email="user6@example.com", is_active=False,
        updated_at="2026-10-27T08:00:00Z",
    )  # fmt: skip
    assert await run(container) == 0
    await issue(client, staff["admin"], poa(12, "2026-11-12", "3"))
    assert await run(container, NOON - timedelta(hours=3)) == 0  # 06:30 по Ташкенту — рано
    assert await run(container) == 1


async def test_no_recipients_means_no_event_and_the_reminder_waits(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    await issue(client, staff["admin"], poa(5, "2026-11-12"))
    await seed_employee(
        container, 9, full_name="Админ Админов", email="user9@example.com",
        permissions={"eds": ["memos.create"]}, updated_at="2026-10-27T08:00:00Z",
    )  # fmt: skip
    assert await run(container) == 0
    assert await outbox(container, "signing_authority.expiring") == []
    await seed_employee(
        container, 9, full_name="Админ Админов", email="user9@example.com",
        permissions={"eds": ["signing.manage"]}, updated_at="2026-10-28T08:00:00Z",
    )  # fmt: skip
    assert await run(container) == 1  # получатель появился — напоминание не потеряно


async def test_rolled_back_transaction_leaves_no_event_and_no_mark(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    await issue(client, staff["admin"], poa(5, "2026-11-12"))

    class RollbackError(Exception): ...

    async def attempt() -> None:
        async with container.session_factory() as session, session.begin():
            assert await signing_reminders.send_expiry_reminders(session, container.bus, now=NOON) == 1
            raise RollbackError

    with pytest.raises(RollbackError):
        await attempt()
    assert await outbox(container, "signing_authority.expiring") == []
    async with container.session_factory() as session:
        marked = (await session.execute(text("SELECT expiry_notified_for FROM signing_authorities"))).scalar_one()
    assert marked is None
    assert await run(container) == 1  # откат не съел напоминание


def test_example_event_is_in_the_catalog_and_valid() -> None:
    envelope = example("eds/signing_authority.expiring.v1")
    assert envelope["type"] == "uz.railtech.eds.signing_authority.expiring.v1"
    assert date.fromisoformat(envelope["data"]["authority"]["valid_to"]) > date(2026, 11, 5)
