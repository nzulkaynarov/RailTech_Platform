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


async def test_repeat_keeps_rows_and_snapshot(
    sessions: async_sessionmaker[AsyncSession], bus: Any
) -> None:
    await _clients(sessions)
    await republish_clients(sessions)
    first = await _outbox(sessions)
    await republish_clients(sessions)
    both = await _outbox(sessions)

    assert (len(first), len(both)) == (3, 6)
    stamps: dict[int, set[str]] = {}
    for row in both:
        snap = row["envelope"]["data"]["client"]
        stamps.setdefault(snap["crm_client_id"], set()).add(snap["updated_at"])
    assert all(len(s) == 1 for s in stamps.values())  # same updated_at: "not older" applies


def test_cli_arguments() -> None:
    from app import __main__ as entry

    parsed = entry._parser().parse_args(["republish-clients", "--client-id", "7", "--dry-run"])
    assert (parsed.command, parsed.client_id, parsed.dry_run) == ("republish-clients", 7, True)
    default = entry._parser().parse_args(["republish-clients"])
    assert (default.client_id, default.dry_run) == (None, False)
