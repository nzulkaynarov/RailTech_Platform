"""Автопереопубликация прав EDS при смене каталога (W13C-F4, Q-W13-A2-3) на настоящем Postgres."""

import asyncio
import time
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


async def test_lock_held_by_another_session_is_skipped_within_the_limit(
    sessions: async_sessionmaker[AsyncSession], bus: Any
) -> None:
    await _staff(sessions)
    async with sessions() as holder, holder.begin():
        await holder.execute(identity_catalog._LOCK_SQL)  # «зависший» держатель

        started = time.monotonic()
        result = await ensure_eds_rights_published(sessions, fingerprint="v-a", lock_timeout_s=0.5)
        elapsed = time.monotonic() - started

        assert (result.republished, result.skipped_locked) == (False, True)
        assert await _outbox_subjects(sessions) == []
        assert await _stored(sessions) == []
        assert 0.4 < elapsed < 10  # ждали предел, а не 30 с по умолчанию

    retry = await ensure_eds_rights_published(sessions, fingerprint="v-a")  # блокировка снята
    assert (retry.republished, retry.users) == (True, 3)


# Отпечаток каталога в формате до D1-8 (main a7c55df73: только коды EDS, `v: 1`) на нынешних данных.
PRE_D1_8_FINGERPRINT = "e63fc509f2738a144af1918be11b5cfd62d054f8481e4d62b5d964be60a92106"


async def test_state_written_before_d1_8_triggers_a_republish_with_sections(
    sessions: async_sessionmaker[AsyncSession], bus: Any
) -> None:
    """Выкладка D1-8: в базе отпечаток старого формата -> при старте воркера все сотрудники
    переопубликованы, и в снимках уже есть `permissions.sections` (EDS заполнит проекцию)."""
    ids = await _staff(sessions)
    async with sessions() as session, session.begin():
        await session.execute(
            text(
                "INSERT INTO identity_catalog_state (key, fingerprint, published_users) "
                "VALUES (:k, :f, 3)"
            ),
            {"k": EDS_KEY, "f": PRE_D1_8_FINGERPRINT},
        )
    assert eds_catalog_fingerprint() != PRE_D1_8_FINGERPRINT

    await sync_eds_rights_on_start(sessions)

    assert sorted(await _outbox_subjects(sessions)) == sorted(f"user/{i}" for i in ids)
    async with sessions() as session:
        rows = await session.execute(
            text("SELECT envelope FROM rt_bus_outbox WHERE type = :t"), {"t": USER_UPDATED}
        )
        permissions = [r[0]["data"]["user"]["permissions"] for r in rows]
    assert len(permissions) == 3
    assert all("sections" in p and "eds" in p for p in permissions)


# --- права ERP (D2-1, B-073): провижининг заново по отпечатку ERP-части каталога ----------------


async def test_changed_erp_fingerprint_provisions_active_erp_staff_once(
    sessions: async_sessionmaker[AsyncSession], bus: Any
) -> None:
    from app.services.identity_catalog import ERP_KEY, ensure_erp_rights_provisioned

    ids = await _staff(sessions, inactive=1)  # ids[0] неактивен
    async with sessions() as session, session.begin():
        await session.execute(
            text("UPDATE users SET platform_access = CAST(:access AS jsonb) WHERE id = ANY(:ids)"),
            {"access": '["crm", "erp"]', "ids": [ids[0], ids[1]]},
        )
    calls: list[tuple[str, int]] = []

    async def enqueue(action: str, user_id: int) -> None:
        calls.append((action, user_id))

    first = await ensure_erp_rights_provisioned(sessions, enqueue, fingerprint="erp-a")
    again = await ensure_erp_rights_provisioned(sessions, enqueue, fingerprint="erp-a")
    changed = await ensure_erp_rights_provisioned(sessions, enqueue, fingerprint="erp-b")

    # Только активный сотрудник с доступом к ERP; без ERP и неактивный — нет.
    assert (first.republished, first.users) == (True, 1)
    assert (again.republished, again.users) == (False, 0)
    assert (changed.republished, changed.users) == (True, 1)
    assert calls == [("provision", ids[1]), ("provision", ids[1])]
    assert (ERP_KEY, "erp-b", 1) in await _stored(sessions)
    assert await _outbox_subjects(sessions) == [], "права ERP — провижинингом, не событиями"


def test_erp_fingerprint_follows_erp_part_of_catalog() -> None:
    from app.domain.platform_roles import erp_catalog_fingerprint

    assert erp_catalog_fingerprint() == erp_catalog_fingerprint()
    assert erp_catalog_fingerprint() != eds_catalog_fingerprint()
