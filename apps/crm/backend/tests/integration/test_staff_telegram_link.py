"""Привязка Telegram сотрудником самим (W15-H6): код одноразовый, истекает, чужой не ломает."""

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain import staff_telegram as rules
from app.domain.errors import ConflictError
from app.models.auth import AuditLog, StaffTelegramLink, User
from app.security.audit import Actor
from app.services.staff_telegram_link import StaffTelegramLinkService
from tests.integration.crm_helpers import make_user

pytestmark = pytest.mark.integration
NOW = datetime(2026, 10, 27, 10, 0, tzinfo=UTC)


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now


class FakeBotState:
    def __init__(self, snap: Any = "running") -> None:
        self.snap = (
            SimpleNamespace(alive=True, username="rt_demo_bot") if snap == "running" else snap
        )

    async def snapshot(self) -> Any:
        return self.snap


def make(
    sessions: async_sessionmaker[AsyncSession], bot: Any = None
) -> tuple[StaffTelegramLinkService, Clock]:
    clock = Clock()
    return StaffTelegramLinkService(sessions, bot or FakeBotState(), clock), clock


def code_of(url: str) -> str:
    code = rules.staff_code_of(url.split("start=", 1)[1])
    assert code is not None
    return code


async def user_row(sessions: async_sessionmaker[AsyncSession], user_id: int) -> User:
    async with sessions() as session:
        user = await session.get(User, user_id)
    assert user is not None
    return user


async def test_link_flow_links_once(sessions: async_sessionmaker[AsyncSession]) -> None:
    svc, _ = make(sessions)
    manager, _ = await make_user(sessions, "dilshod@railtech.uz", ["manager"])
    ticket = await svc.begin(manager.id)
    assert ticket.url.startswith("https://t.me/rt_demo_bot?start=staff_")
    assert ticket.expires_at == NOW + rules.CODE_TTL
    code = code_of(ticket.url)

    # В БД только хеш, не сам код.
    async with sessions() as session:
        stored = (await session.scalars(select(StaffTelegramLink.code_hash))).all()
    assert stored == [rules.hash_code(code)]
    assert code not in stored[0]

    outcome = await svc.confirm(code, 777001, "@dilshod_t")
    assert outcome.status == "linked"
    user = await user_row(sessions, manager.id)
    assert (user.tg_user_id, user.tg_username) == (777001, "dilshod_t")

    # Повторное использование того же кода — отказ.
    assert (await svc.confirm(code, 777002, "intruder")).status == "invalid"
    assert (await user_row(sessions, manager.id)).tg_user_id == 777001
    async with sessions() as session:
        actions = list(await session.scalars(select(AuditLog.action)))
    assert "user.telegram_linked" in actions


async def test_code_expires(sessions: async_sessionmaker[AsyncSession]) -> None:
    svc, clock = make(sessions)
    manager, _ = await make_user(sessions, "dilshod@railtech.uz", ["manager"])
    code = code_of((await svc.begin(manager.id)).url)
    clock.now = NOW + rules.CODE_TTL  # граница включена в «истёк»
    assert (await svc.confirm(code, 777001, None)).status == "invalid"
    assert (await user_row(sessions, manager.id)).tg_user_id is None


async def test_new_link_cancels_the_previous_one(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    svc, _ = make(sessions)
    manager, _ = await make_user(sessions, "dilshod@railtech.uz", ["manager"])
    first = code_of((await svc.begin(manager.id)).url)
    second = code_of((await svc.begin(manager.id)).url)
    assert (await svc.confirm(first, 777001, None)).status == "invalid"
    assert (await svc.confirm(second, 777001, None)).status == "linked"


async def test_unknown_code_is_invalid(sessions: async_sessionmaker[AsyncSession]) -> None:
    svc, _ = make(sessions)
    assert (await svc.confirm(rules.new_code(), 1, None)).status == "invalid"


async def test_telegram_already_linked_to_a_colleague_is_taken(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    svc, _ = make(sessions)
    first, _ = await make_user(sessions, "first@railtech.uz", ["manager"])
    second, _ = await make_user(sessions, "second@railtech.uz", ["manager"])
    assert (
        await svc.confirm(code_of((await svc.begin(first.id)).url), 5001, "a")
    ).status == "linked"
    outcome = await svc.confirm(code_of((await svc.begin(second.id)).url), 5001, "a")
    assert outcome.status == "taken"
    assert (await user_row(sessions, second.id)).tg_user_id is None
    assert (await user_row(sessions, first.id)).tg_user_id == 5001


async def test_deactivated_employee_cannot_link(sessions: async_sessionmaker[AsyncSession]) -> None:
    svc, _ = make(sessions)
    manager, _ = await make_user(sessions, "dilshod@railtech.uz", ["manager"])
    code = code_of((await svc.begin(manager.id)).url)
    async with sessions() as session, session.begin():
        await session.execute(update(User).where(User.id == manager.id).values(is_active=False))
    assert (await svc.confirm(code, 5001, None)).status == "invalid"


async def test_unlink_clears_everything(sessions: async_sessionmaker[AsyncSession]) -> None:
    svc, _ = make(sessions)
    manager, _ = await make_user(sessions, "dilshod@railtech.uz", ["manager"])
    await svc.confirm(code_of((await svc.begin(manager.id)).url), 5001, "dilshod_t")
    pending = code_of((await svc.begin(manager.id)).url)

    await svc.unlink(Actor(manager.id), manager.id)
    user = await user_row(sessions, manager.id)
    assert (user.tg_user_id, user.tg_username) == (None, None)
    assert (await svc.confirm(pending, 5001, None)).status == "invalid"  # висящий код погашен
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(StaffTelegramLink)) == 0
    # Отвязка без привязки — не ошибка.
    await svc.unlink(Actor(manager.id), manager.id)


@pytest.mark.parametrize(
    ("snap", "reason"),
    [
        (None, "bot_not_configured"),
        (SimpleNamespace(alive=False, username=None), "bot_not_running"),
        (SimpleNamespace(alive=True, username=None), "bot_not_running"),
    ],
)
async def test_no_link_without_a_running_bot(
    sessions: async_sessionmaker[AsyncSession], snap: Any, reason: str
) -> None:
    svc, _ = make(sessions, FakeBotState(snap))
    manager, _ = await make_user(sessions, "dilshod@railtech.uz", ["manager"])
    with pytest.raises(ConflictError) as caught:
        await svc.begin(manager.id)
    assert caught.value.details["reason"] == reason
