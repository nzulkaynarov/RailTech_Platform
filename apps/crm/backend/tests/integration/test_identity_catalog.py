"""Автопереопубликация прав EDS при смене каталога (W13C-F4, Q-W13-A2-3) на настоящем Postgres."""

import asyncio
from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bus import runtime
from app.bus.runtime import build_bus
from app.domain.platform_roles import eds_catalog_fingerprint
from app.services import identity_catalog, identity_republish
from app.services.identity_catalog import (
    EDS_KEY,
    ensure_eds_rights_published,
    sync_eds_rights_on_start,
)
from tests.integration.crm_helpers import make_user

pytestmark = pytest.mark.integration
USER_UPDATED = "uz.railtech.identity.user.updated.v1"
STAFF = [("dilshod", "manager"), ("aziza", "manager"), ("boss", "admin")]


@pytest.fixture
def bus(sessions: async_sessionmaker[AsyncSession]) -> Iterator[Any]:
    stand = build_bus(sessions, None)
    runtime.set_bus(stand)
    yield stand
    runtime.set_bus(None)


async def _staff(sessions: async_sessionmaker[AsyncSession], *, inactive: int = 0) -> list[int]:
    ids = [(await make_user(sessions, f"{n}@railtech.uz", [role]))[0].id for n, role in STAFF]
    async with sessions() as session, session.begin():
        if inactive:
            await session.execute(
                text("UPDATE users SET is_active = false WHERE id = :i"), {"i": ids[0]}
            )
        await session.execute(text("DELETE FROM rt_bus_outbox"))  # создание тоже публикует
    return ids


async def _outbox_subjects(sessions: async_sessionmaker[AsyncSession]) -> list[str]:
    async with sessions() as session:
        rows = await session.execute(
            text("SELECT subject FROM rt_bus_outbox WHERE type = :t ORDER BY id"),
            {"t": USER_UPDATED},
        )
        return [r[0] for r in rows]


async def _stored(sessions: async_sessionmaker[AsyncSession]) -> list[Any]:
    async with sessions() as session:
        rows = await session.execute(
            text("SELECT key, fingerprint, published_users FROM identity_catalog_state")
        )
        return [tuple(r) for r in rows]


async def test_changed_fingerprint_publishes_everyone_once_then_nothing(
    sessions: async_sessionmaker[AsyncSession], bus: Any
) -> None:
    ids = await _staff(sessions, inactive=1)  # неактивные — тоже (как у команды)

    first = await ensure_eds_rights_published(sessions, fingerprint="v-a")
    again = await ensure_eds_rights_published(sessions, fingerprint="v-a")  # «повторный старт»

    assert (first.republished, first.users) == (True, 3)
    assert (again.republished, again.users) == (False, 0)
    assert sorted(await _outbox_subjects(sessions)) == sorted(f"user/{i}" for i in ids)
    assert await _stored(sessions) == [(EDS_KEY, "v-a", 3)]


async def test_next_catalog_change_republishes_again(
    sessions: async_sessionmaker[AsyncSession], bus: Any
) -> None:
    await _staff(sessions)
    await ensure_eds_rights_published(sessions, fingerprint="v-a")

    second = await ensure_eds_rights_published(sessions, fingerprint="v-b")

    assert (second.republished, second.users) == (True, 3)
    assert len(await _outbox_subjects(sessions)) == 6
    assert await _stored(sessions) == [(EDS_KEY, "v-b", 3)]


async def test_default_fingerprint_is_the_catalog_one(
    sessions: async_sessionmaker[AsyncSession], bus: Any
) -> None:
    await _staff(sessions)

    await ensure_eds_rights_published(sessions)

    assert await _stored(sessions) == [(EDS_KEY, eds_catalog_fingerprint(), 3)]
    assert (await ensure_eds_rights_published(sessions)).republished is False


async def test_first_start_on_clean_database_records_fingerprint_without_events(
    sessions: async_sessionmaker[AsyncSession], bus: Any
) -> None:
    result = await ensure_eds_rights_published(sessions, fingerprint="v-a")

    assert (result.republished, result.users) == (True, 0)
    assert await _outbox_subjects(sessions) == []
    assert await _stored(sessions) == [(EDS_KEY, "v-a", 0)]


async def test_two_concurrent_starts_publish_once(
    sessions: async_sessionmaker[AsyncSession], bus: Any
) -> None:
    await _staff(sessions)

    results = await asyncio.gather(
        *(ensure_eds_rights_published(sessions, fingerprint="v-a") for _ in range(3))
    )

    assert sorted(r.republished for r in results) == [False, False, True]
    assert len(await _outbox_subjects(sessions)) == 3  # по событию на сотрудника, не 9
    assert await _stored(sessions) == [(EDS_KEY, "v-a", 3)]


async def test_failure_keeps_old_fingerprint_and_next_start_retries(
    sessions: async_sessionmaker[AsyncSession], bus: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _staff(sessions)
    await ensure_eds_rights_published(sessions, fingerprint="v-a")
    real = identity_republish.republish_identity

    async def broken(*args: Any, **kwargs: Any) -> Any:
        raise ConnectionError("шина недоступна")

    monkeypatch.setattr(identity_catalog, "republish_identity", broken)
    with pytest.raises(ConnectionError):
        await ensure_eds_rights_published(sessions, fingerprint="v-b")
    assert await _stored(sessions) == [(EDS_KEY, "v-a", 3)]  # отпечаток не сдвинут

    monkeypatch.setattr(identity_catalog, "republish_identity", real)
    retry = await ensure_eds_rights_published(sessions, fingerprint="v-b")
    assert (retry.republished, retry.users) == (True, 3)
    assert await _stored(sessions) == [(EDS_KEY, "v-b", 3)]


async def test_start_hook_swallows_failures(
    sessions: async_sessionmaker[AsyncSession], bus: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _staff(sessions)

    async def broken(*args: Any, **kwargs: Any) -> Any:
        raise ConnectionError("база недоступна")

    monkeypatch.setattr(identity_catalog, "ensure_eds_rights_published", broken)
    await sync_eds_rights_on_start(sessions)  # не бросает: старт воркера не зависит от шины

    monkeypatch.undo()
    await sync_eds_rights_on_start(sessions)  # следующий старт делает работу
    assert len(await _outbox_subjects(sessions)) == 3
