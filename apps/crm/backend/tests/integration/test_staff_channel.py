"""Team channel and client groups as staff membership (ОНБ-1.2), with a fake bot.

Deactivation or unlinking removes the employee from the team channel and client groups (ban + unban,
so he can be invited again); a join request is approved only for an active linked employee; the bot
sends a join-request link after linking; a daily job removes deactivated staff who are still inside.
"""

from types import SimpleNamespace
from typing import Any

import pytest
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError
from aiogram.methods import TelegramMethod
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bot import staff_channel as join_router
from app.models.auth import AuditLog, User
from app.models.integrations import TelegramGroup
from app.security.audit import Actor
from app.services.settings import SettingsService
from app.services.staff_channel import StaffChannelService, StaffChannelUnavailableError
from app.services.staff_telegram_link import StaffTelegramLinkService
from app.services.user_views import UserPatch
from app.services.users import UserService
from tests.integration.crm_helpers import make_user

pytestmark = pytest.mark.integration
TEAM = -1001800000001
GROUP = -1001800000002
TG = 9001
BOT_ID = 777


class FakeBot(Bot):
    """Bot API without network: calls are recorded, member statuses are scripted."""

    def __init__(self) -> None:
        super().__init__("777:fake-token-for-tests-0000")
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.members: dict[tuple[int, int], str] = {}
        self.bot_rights: dict[int, Any] = {}
        self.fail: dict[str, Exception] = {}

    async def __call__(
        self, method: TelegramMethod[Any], request_timeout: int | None = None
    ) -> Any:
        name = type(method).__name__
        data = method.model_dump(exclude_none=True)
        self.calls.append((name, data))
        if name in self.fail:
            raise self.fail[name]
        if name == "GetMe":
            return SimpleNamespace(id=BOT_ID, is_bot=True, first_name="bot", username="rt_bot")
        if name == "GetChatMember":
            if data["user_id"] == BOT_ID:
                return self.bot_rights[data["chat_id"]]
            status = self.members.get((data["chat_id"], data["user_id"]), "left")
            return SimpleNamespace(status=status)
        if name == "CreateChatInviteLink":
            return SimpleNamespace(invite_link="https://t.me/+join-request")
        return True

    def names(self) -> list[str]:
        return [name for name, _ in self.calls]


@pytest.fixture
def bot() -> FakeBot:
    return FakeBot()


@pytest.fixture
def service(sessions: async_sessionmaker[AsyncSession], bot: FakeBot) -> StaffChannelService:
    async def provider() -> FakeBot:
        return bot

    return StaffChannelService(sessions, SettingsService(sessions, ttl_s=0), provider)


@pytest.fixture(autouse=True)
async def chats(sessions: async_sessionmaker[AsyncSession]) -> None:
    settings = SettingsService(sessions, ttl_s=0)
    current = (await settings.raw())["notifications"]
    await settings.update("notifications", {**current, "channel_id": TEAM}, None)
    async with sessions() as session, session.begin():
        session.add(TelegramGroup(chat_id=GROUP, title="Клиент", chat_type="supergroup"))


async def linked_user(
    sessions: async_sessionmaker[AsyncSession], email: str = "karim@railtech.uz"
) -> int:
    account, _ = await make_user(sessions, email, ["manager"])
    async with sessions() as session, session.begin():
        await session.execute(update(User).where(User.id == account.id).values(tg_user_id=TG))
    return account.id


def inside(bot: FakeBot) -> None:
    bot.members[(TEAM, TG)] = "member"
    bot.members[(GROUP, TG)] = "member"


async def journal(sessions: async_sessionmaker[AsyncSession], action: str) -> list[AuditLog]:
    async with sessions() as session:
        rows = await session.scalars(select(AuditLog).where(AuditLog.action == action))
        return list(rows)


# --- removal ---------------------------------------------------------------------------------


async def test_deactivation_removes_him_from_team_channel_and_groups(
    sessions: async_sessionmaker[AsyncSession], service: StaffChannelService, bot: FakeBot
) -> None:
    user_id = await linked_user(sessions)
    inside(bot)
    queued: list[tuple[int, int]] = []

    async def release(uid: int, tg: int) -> None:
        queued.append((uid, tg))

    users = UserService(sessions, on_telegram_released=release)
    await users.update(Actor.system(), user_id, UserPatch(is_active=False))
    assert queued == [(user_id, TG)]

    result = await service.remove_member(user_id, TG)
    assert result.removed == 2
    assert result.failed == []
    bans = [d["chat_id"] for n, d in bot.calls if n == "BanChatMember"]
    unbans = [d for n, d in bot.calls if n == "UnbanChatMember"]
    assert sorted(bans) == sorted([TEAM, GROUP])
    assert len(unbans) == 2
    assert all(d["only_if_banned"] for d in unbans)
    entry = (await journal(sessions, "user.telegram_chats_removed"))[0]
    assert entry.after == {"removed": 2, "failed": []}
    assert entry.entity_id == str(user_id)


async def test_unlinking_telegram_releases_the_account(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    user_id = await linked_user(sessions)
    queued: list[tuple[int, int]] = []

    async def release(uid: int, tg: int) -> None:
        queued.append((uid, tg))

    links = StaffTelegramLinkService(sessions, None, on_released=release)  # type: ignore[arg-type]
    await links.unlink(Actor(user_id), user_id)
    assert queued == [(user_id, TG)]


async def test_admin_clearing_telegram_releases_the_account(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    user_id = await linked_user(sessions)
    queued: list[tuple[int, int]] = []

    async def release(uid: int, tg: int) -> None:
        queued.append((uid, tg))

    await UserService(sessions, on_telegram_released=release).update(
        Actor.system(), user_id, UserPatch(clear_tg_user_id=True)
    )
    assert queued == [(user_id, TG)]


async def test_unrelated_edit_does_not_release(sessions: async_sessionmaker[AsyncSession]) -> None:
    user_id = await linked_user(sessions)
    queued: list[tuple[int, int]] = []

    async def release(uid: int, tg: int) -> None:
        queued.append((uid, tg))

    await UserService(sessions, on_telegram_released=release).update(
        Actor.system(), user_id, UserPatch(full_name="Новое имя")
    )
    assert queued == []


async def test_nothing_is_removed_if_he_is_staff_again(
    sessions: async_sessionmaker[AsyncSession], service: StaffChannelService, bot: FakeBot
) -> None:
    user_id = await linked_user(sessions)  # still active and linked: the task ran late
    inside(bot)
    assert (await service.remove_member(user_id, TG)).removed == 0
    assert bot.calls == []


async def test_outsider_is_skipped_and_not_journaled(
    sessions: async_sessionmaker[AsyncSession], service: StaffChannelService, bot: FakeBot
) -> None:
    bot.members[(GROUP, TG)] = "member"  # not in the team channel
    result = await service.remove_member(1, TG)
    assert result.removed == 1
    assert [d["chat_id"] for n, d in bot.calls if n == "BanChatMember"] == [GROUP]


async def test_bot_without_rights_is_reported_not_raised(
    sessions: async_sessionmaker[AsyncSession], service: StaffChannelService, bot: FakeBot
) -> None:
    inside(bot)
    method: Any = SimpleNamespace()
    bot.fail["BanChatMember"] = TelegramBadRequest(method=method, message="not enough rights")
    result = await service.remove_member(1, TG)
    assert result.removed == 0
    assert sorted(result.failed) == sorted([TEAM, GROUP])
    entry = (await journal(sessions, "user.telegram_chats_removed"))[0]
    assert entry.after == {"removed": 0, "failed": [TEAM, GROUP]}


async def test_transient_failure_raises_so_the_queue_retries(
    service: StaffChannelService, bot: FakeBot
) -> None:
    inside(bot)
    method: Any = SimpleNamespace()
    bot.fail["BanChatMember"] = TelegramNetworkError(method=method, message="timeout")
    with pytest.raises(StaffChannelUnavailableError):
        await service.remove_member(1, TG)


async def test_daily_reconciliation_removes_deactivated_staff_still_inside(
    sessions: async_sessionmaker[AsyncSession], service: StaffChannelService, bot: FakeBot
) -> None:
    gone = await linked_user(sessions)
    await UserService(sessions).update(Actor.system(), gone, UserPatch(is_active=False))
    other, _ = await make_user(sessions, "sanjar@railtech.uz", ["manager"])
    async with sessions() as session, session.begin():
        await session.execute(update(User).where(User.id == other.id).values(tg_user_id=TG + 1))
    inside(bot)
    bot.members[(TEAM, TG + 1)] = "member"  # active colleague: must stay
    assert await service.reconcile() == 2
    assert {d["user_id"] for n, d in bot.calls if n == "BanChatMember"} == {TG}


# --- invite and join request -----------------------------------------------------------------


async def test_invite_link_asks_for_a_join_request(
    service: StaffChannelService, bot: FakeBot
) -> None:
    assert await service.invite_url(TG) == "https://t.me/+join-request"
    created = next(d for n, d in bot.calls if n == "CreateChatInviteLink")
    assert created["chat_id"] == TEAM
    assert created["creates_join_request"] is True
    assert "member_limit" not in created  # incompatible with join requests


async def test_no_invite_when_he_is_already_inside(
    service: StaffChannelService, bot: FakeBot
) -> None:
    bot.members[(TEAM, TG)] = "member"
    assert await service.invite_url(TG) is None
    assert "CreateChatInviteLink" not in bot.names()


async def test_join_request_is_approved_for_active_linked_staff_only(
    sessions: async_sessionmaker[AsyncSession], service: StaffChannelService, bot: FakeBot
) -> None:
    user_id = await linked_user(sessions)

    async def ask(chat: int, tg: int) -> None:
        request: Any = SimpleNamespace(
            chat=SimpleNamespace(id=chat), from_user=SimpleNamespace(id=tg)
        )
        await join_router.on_join_request(request, bot, service)

    await ask(TEAM, TG)
    await ask(TEAM, 4242)  # a stranger
    await ask(GROUP, 4242)  # not the team channel: not ours to answer
    answers = [(n, d["user_id"]) for n, d in bot.calls if "JoinRequest" in n]
    assert answers == [("ApproveChatJoinRequest", TG), ("DeclineChatJoinRequest", 4242)]
    assert (await journal(sessions, "team_channel.join_declined"))[0].after == {"tg_user_id": 4242}
    assert (await journal(sessions, "user.team_channel_joined"))[0].entity_id == str(user_id)

    await UserService(sessions).update(Actor.system(), user_id, UserPatch(is_active=False))
    await ask(TEAM, TG)  # deactivated: declined
    assert bot.calls[-1][0] == "DeclineChatJoinRequest"


# --- the state shown in the existing Telegram settings -------------------------------------------


@pytest.mark.parametrize(
    ("rights", "expected"),
    [
        (SimpleNamespace(status="administrator", can_invite_users=True), True),
        (SimpleNamespace(status="administrator", can_invite_users=False), False),
        (SimpleNamespace(status="creator"), True),
        (SimpleNamespace(status="member"), False),
    ],
)
async def test_bot_invite_right_in_the_team_channel(
    service: StaffChannelService, bot: FakeBot, rights: Any, expected: bool
) -> None:
    bot.bot_rights[TEAM] = rights
    assert await service.can_invite() is expected


async def test_invite_right_is_unknown_when_telegram_fails(
    service: StaffChannelService, bot: FakeBot
) -> None:
    method: Any = SimpleNamespace()
    bot.fail["GetChatMember"] = TelegramNetworkError(method=method, message="timeout")
    assert await service.can_invite() is None
