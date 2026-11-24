"""`republish-clients` on real Postgres: current `client.updated.v1` snapshots go through the
outbox with the same builder as the normal update path (owner included)."""

from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bus import events as bus_events
from app.bus import runtime
from app.bus.runtime import build_bus
from app.models.clients import Client
from app.models.leads import Lead
from app.security.audit import Actor
from app.services.client_republish import republish_clients
from tests.integration.crm_helpers import make_user

pytestmark = pytest.mark.integration
CLIENT_UPDATED = "uz.railtech.crm.client.updated.v1"


@pytest.fixture
def bus(sessions: async_sessionmaker[AsyncSession]) -> Iterator[Any]:
    stand = build_bus(sessions, None)
    runtime.set_bus(stand)
    yield stand
    runtime.set_bus(None)


async def _clear_outbox(sessions: async_sessionmaker[AsyncSession]) -> None:
    async with sessions() as session, session.begin():
        await session.execute(text("DELETE FROM rt_bus_outbox"))


async def _clients(sessions: async_sessionmaker[AsyncSession]) -> list[int]:
    owner = (await make_user(sessions, "owner@railtech.uz", ["manager"]))[0].id
    async with sessions() as session, session.begin():
        rows = [
            Client(name="ООО Один", owner_user_id=owner),
            Client(name="ООО Два", inn="123456789"),
            Client(name="ООО Три", owner_user_id=owner),
        ]
        session.add_all(rows)
        await session.flush()
        # A client whose lead never gave consent: the normal path has no consent gate either.
        session.add(Lead(display_name="Без согласия", stage="customer", client_id=rows[1].id))
        ids = [row.id for row in rows]
    await _clear_outbox(sessions)
    return ids


async def _outbox(sessions: async_sessionmaker[AsyncSession]) -> list[dict[str, Any]]:
    async with sessions() as session:
        rows = (
            await session.execute(
                text("SELECT type, subject, envelope FROM rt_bus_outbox ORDER BY created_at, id")
            )
        ).mappings()
        return [dict(row) for row in rows]


async def test_dry_run_counts_and_writes_nothing(
    sessions: async_sessionmaker[AsyncSession], bus: Any
) -> None:
    await _clients(sessions)

    result = await republish_clients(sessions, dry_run=True)

    assert (result.clients, result.published) == (3, 0)
    assert await _outbox(sessions) == []


async def test_publishes_one_snapshot_per_client_equal_to_the_normal_path(
    sessions: async_sessionmaker[AsyncSession], bus: Any
) -> None:
    ids = await _clients(sessions)

    result = await republish_clients(sessions, batch_size=2)  # two batches: 2 + 1
    rows = await _outbox(sessions)
    await _clear_outbox(sessions)
    async with sessions() as session, session.begin():  # the normal path, same builder
        for cid in ids:
            client = await session.get(Client, cid)
            assert client is not None
            await bus_events.client_updated(session, client, Actor.system())
    normal = await _outbox(sessions)

    assert (result.clients, result.published) == (3, 3)
    assert {row["type"] for row in rows} == {CLIENT_UPDATED}
    assert sorted(row["subject"] for row in rows) == sorted(f"client/{i}" for i in ids)
    assert len({row["envelope"]["id"] for row in rows}) == 3
    by_subject = {row["subject"]: row["envelope"]["data"] for row in rows}
    assert by_subject == {row["subject"]: row["envelope"]["data"] for row in normal}
    assert by_subject[f"client/{ids[0]}"]["client"]["owner"]["full_name"]  # the point of the run
    assert by_subject[f"client/{ids[1]}"]["client"]["owner"] is None


async def test_client_id_limits_and_unknown_id_publishes_nothing(
    sessions: async_sessionmaker[AsyncSession], bus: Any
) -> None:
    ids = await _clients(sessions)

    one = await republish_clients(sessions, client_id=ids[1])
    missing = await republish_clients(sessions, client_id=999_999)

    rows = await _outbox(sessions)
    assert [row["subject"] for row in rows] == [f"client/{ids[1]}"]
    assert (one.clients, one.published) == (1, 1)
    assert (missing.clients, missing.published) == (0, 0)


async def test_republish_keeps_rows_and_repeats_the_last_published_snapshot(
    sessions: async_sessionmaker[AsyncSession], bus: Any
) -> None:
    """The client row is not changed: the snapshot equals the last published one (ERP applies the
    same moment for the owner it did not store before, #763), a repeat gives the same snapshot."""
    ids = await _clients(sessions)
    async with sessions() as session, session.begin():  # the normal path: last published state
        for cid in ids:
            client = await session.get(Client, cid)
            assert client is not None
            await bus_events.client_updated(session, client, Actor.system())
    last = {row["subject"]: row["envelope"]["data"]["client"] for row in await _outbox(sessions)}
    await _clear_outbox(sessions)

    await republish_clients(sessions)
    first = {row["subject"]: row["envelope"]["data"]["client"] for row in await _outbox(sessions)}
    await republish_clients(sessions)
    rows = await _outbox(sessions)

    assert first == last
    assert len(rows) == 2 * len(ids)
    assert all(r["envelope"]["data"]["client"] == last[r["subject"]] for r in rows)


def test_cli_arguments() -> None:
    from app import __main__ as entry

    parsed = entry._parser().parse_args(["republish-clients", "--client-id", "7", "--dry-run"])
    assert (parsed.command, parsed.client_id, parsed.dry_run) == ("republish-clients", 7, True)
    default = entry._parser().parse_args(["republish-clients"])
    assert (default.client_id, default.dry_run) == (None, False)


CONTACT_UPDATED = "uz.railtech.crm.contact.updated.v1"


async def _handed_over(sessions: async_sessionmaker[AsyncSession]) -> tuple[int, int]:
    """One handed-over client with two contacts and one client not handed over (with a contact)."""
    from app.models.clients import ClientContact

    async with sessions() as session, session.begin():
        done = Client(name="ООО Передан", erp_company_id=7)
        waiting = Client(name="ООО Ждёт")
        session.add_all([done, waiting])
        await session.flush()
        session.add_all(
            [
                ClientContact(client_id=done.id, full_name="А", position="Директор"),
                ClientContact(client_id=done.id, full_name="Б"),
                ClientContact(client_id=waiting.id, full_name="В"),
            ]
        )
        ids = (done.id, waiting.id)
    await _clear_outbox(sessions)
    return ids


async def test_republish_contacts_dry_run_counts_and_writes_nothing(
    sessions: async_sessionmaker[AsyncSession], bus: Any
) -> None:
    from app.services.client_republish import republish_handed_over_contacts

    await _handed_over(sessions)

    result = await republish_handed_over_contacts(sessions, dry_run=True)

    assert (result.clients, result.contacts, result.published) == (1, 2, 0)
    assert await _outbox(sessions) == []


async def test_republish_contacts_publishes_only_handed_over_clients_and_is_repeatable(
    sessions: async_sessionmaker[AsyncSession], bus: Any
) -> None:
    from app.services.client_republish import republish_handed_over_contacts

    done_id, _ = await _handed_over(sessions)

    result = await republish_handed_over_contacts(sessions, dry_run=False)

    assert (result.clients, result.published) == (1, 2)
    rows = await _outbox(sessions)
    assert {r["type"] for r in rows} == {CONTACT_UPDATED}
    snapshots = [r["envelope"]["data"]["contact"] for r in rows]
    assert {s["crm_client_id"] for s in snapshots} == {done_id}
    assert sorted(s["full_name"] for s in snapshots) == ["А", "Б"]
    assert {s["position"] for s in snapshots} == {"Директор", None}
    # The snapshot moment is the contact's own `updated_at`: a repeat carries the same moment, so
    # ERP applies it once (see test_crm_projections) and the CRM rows are not touched.
    again = await republish_handed_over_contacts(sessions, dry_run=False)
    assert again.published == 2
    moments = {s["updated_at"] for s in snapshots}
    rows = await _outbox(sessions)
    assert {r["envelope"]["data"]["contact"]["updated_at"] for r in rows} == moments


async def _phones_world(sessions: async_sessionmaker[AsyncSession]) -> None:
    from app.models.clients import ClientContact

    async with sessions() as session, session.begin():
        done = Client(name="ООО Телефоны", erp_company_id=9)
        session.add(done)
        await session.flush()
        session.add_all(
            [
                ClientContact(client_id=done.id, full_name="Сырой", phone_e164="90 123 45 67"),
                ClientContact(client_id=done.id, full_name="Чистый", phone_e164="+998901112233"),
                ClientContact(client_id=done.id, full_name="Мусор", phone_e164="abc"),
                ClientContact(client_id=done.id, full_name="Местный", phone_e164="8 90 123 45 67"),
                ClientContact(client_id=done.id, full_name="Без", phone_e164=None),
            ]
        )
    await _clear_outbox(sessions)


async def test_republish_contacts_dry_run_reports_phones_and_changes_nothing(
    sessions: async_sessionmaker[AsyncSession], bus: Any
) -> None:
    from app.services.client_republish import republish_handed_over_contacts

    await _phones_world(sessions)

    result = await republish_handed_over_contacts(sessions, dry_run=True)

    assert (result.contacts, result.phones_to_fix, result.phones_unparseable) == (5, 1, 2)
    assert await _outbox(sessions) == []
    async with sessions() as session:
        phones = set((await session.scalars(text_select_phones())).all())
    assert "90 123 45 67" in phones


def text_select_phones() -> Any:
    from sqlalchemy import select

    from app.models.clients import ClientContact

    return select(ClientContact.phone_e164)


async def test_republish_contacts_normalises_phones_and_never_blanks_unparseable_ones(
    sessions: async_sessionmaker[AsyncSession], bus: Any
) -> None:
    from app.services.client_republish import republish_handed_over_contacts

    await _phones_world(sessions)

    result = await republish_handed_over_contacts(sessions, dry_run=False)

    assert result.published == 3  # raw (fixed), clean, no phone; the two unparseable are skipped
    snapshots = {
        r["envelope"]["data"]["contact"]["full_name"]: r["envelope"]["data"]["contact"]
        for r in await _outbox(sessions)
    }
    assert set(snapshots) == {"Сырой", "Чистый", "Без"}
    assert snapshots["Сырой"]["phone_e164"] == "+998901234567"
    assert snapshots["Чистый"]["phone_e164"] == "+998901112233"
    assert snapshots["Без"]["phone_e164"] is None
    async with sessions() as session:
        phones = set((await session.scalars(text_select_phones())).all())
    assert phones == {"+998901234567", "+998901112233", "abc", "8 90 123 45 67", None}
