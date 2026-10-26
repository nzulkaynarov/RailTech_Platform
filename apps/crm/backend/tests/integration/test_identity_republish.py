"""Команда `republish-identity` (E7b, C1-G-3) на настоящем Postgres: снимки всех сотрудников
уходят на шину событиями `identity.user.updated.v1` через outbox — для подписчика, который появился
позже сотрудников (EDS)."""

from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bus import runtime
from app.bus.runtime import build_bus
from app.models.auth import User
from app.services.identity_republish import republish_identity
from tests.integration.crm_helpers import make_user

pytestmark = pytest.mark.integration
USER_UPDATED = "uz.railtech.identity.user.updated.v1"


@pytest.fixture
def bus(sessions: async_sessionmaker[AsyncSession]) -> Iterator[Any]:
    stand = build_bus(sessions, None)
    runtime.set_bus(stand)
    yield stand
    runtime.set_bus(None)


async def _staff(sessions: async_sessionmaker[AsyncSession]) -> list[int]:
    ids = [(await make_user(sessions, f"{n}@railtech.uz", [role]))[0].id for n, role in STAFF]
    async with sessions() as session, session.begin():
        await session.execute(text("DELETE FROM rt_bus_outbox"))  # создание тоже публикует
    return ids


STAFF = [("dilshod", "manager"), ("aziza", "manager"), ("boss", "admin")]


async def _row_stamps(sessions: async_sessionmaker[AsyncSession]) -> dict[int, Any]:
    async with sessions() as session:
        return {u.id: u.updated_at for u in await session.scalars(select(User))}


async def _outbox(sessions: async_sessionmaker[AsyncSession]) -> list[dict[str, Any]]:
    async with sessions() as session:
        rows = (
            await session.execute(
                text("SELECT type, subject, envelope FROM rt_bus_outbox ORDER BY created_at, id")
            )
        ).mappings()
        return [dict(row) for row in rows]


async def test_publishes_full_snapshot_for_every_staff_member(
    sessions: async_sessionmaker[AsyncSession], bus: Any
) -> None:
    ids = await _staff(sessions)

    result = await republish_identity(sessions, batch_size=2)  # две пачки: 2 + 1

    rows = await _outbox(sessions)
    assert (result.users, result.published) == (3, 3)
    assert {row["type"] for row in rows} == {USER_UPDATED}
    assert sorted(row["subject"] for row in rows) == sorted(f"user/{i}" for i in ids)
    for row in rows:
        data = row["envelope"]["data"]
        assert "changed_fields" not in data  # необязательное поле: менять нечего
        assert data["actor"] == {"type": "system"}
        assert set(data["user"]["permissions"]) == {"eds"}
        assert data["user"]["email"].endswith("@railtech.uz")
    assert len({row["envelope"]["id"] for row in rows}) == 3


async def test_repeat_gives_new_event_ids_with_the_same_snapshot_and_keeps_rows(
    sessions: async_sessionmaker[AsyncSession], bus: Any
) -> None:
    await _staff(sessions)
    stamps_before = await _row_stamps(sessions)
    first = await republish_identity(sessions)
    one = await _outbox(sessions)
    second = await republish_identity(sessions)
    both = await _outbox(sessions)

    assert (first.published, second.published) == (3, 3)
    assert len(both) == 6
    assert len({r["envelope"]["id"] for r in both}) == 6
    by_user: dict[int, set[str]] = {}
    for row in both:
        user = row["envelope"]["data"]["user"]
        by_user.setdefault(user["crm_user_id"], set()).add(user["updated_at"])
    assert all(len(stamps) == 1 for stamps in by_user.values())  # тот же updated_at: «не старее»
    assert len(one) == 3
    assert await _row_stamps(sessions) == stamps_before  # строки сотрудников не тронуты


async def test_dry_run_counts_and_publishes_nothing(
    sessions: async_sessionmaker[AsyncSession], bus: Any
) -> None:
    await _staff(sessions)

    result = await republish_identity(sessions, dry_run=True)

    assert (result.users, result.published) == (3, 0)
    assert await _outbox(sessions) == []


async def test_single_user_by_id_and_unknown_id(
    sessions: async_sessionmaker[AsyncSession], bus: Any
) -> None:
    ids = await _staff(sessions)

    result = await republish_identity(sessions, user_id=ids[1])
    missing = await republish_identity(sessions, user_id=999_999)

    rows = await _outbox(sessions)
    assert [row["subject"] for row in rows] == [f"user/{ids[1]}"]
    assert (result.users, result.published) == (1, 1)
    assert (missing.users, missing.published) == (0, 0)


async def test_deactivated_user_is_republished_with_empty_eds(
    sessions: async_sessionmaker[AsyncSession], bus: Any
) -> None:
    ids = await _staff(sessions)
    async with sessions() as session, session.begin():
        await session.execute(
            text("UPDATE users SET is_active = false WHERE id = :i"), {"i": ids[0]}
        )

    await republish_identity(sessions, user_id=ids[0])

    (row,) = await _outbox(sessions)
    user = row["envelope"]["data"]["user"]
    assert (user["is_active"], user["permissions"]["eds"]) == (False, [])


def test_cli_arguments() -> None:
    from app import __main__ as entry

    parsed = entry._parser().parse_args(["republish-identity", "--user-id", "7", "--dry-run"])
    assert (parsed.command, parsed.user_id, parsed.dry_run) == ("republish-identity", 7, True)
    default = entry._parser().parse_args(["republish-identity"])
    assert (default.user_id, default.dry_run) == (None, False)
