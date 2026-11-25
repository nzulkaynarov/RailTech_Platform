"""Team channel and client groups as staff membership (ОНБ-1.2), with a fake bot.

Deactivation or unlinking removes the employee from the team channel and client groups (ban + unban,
so he can be invited again); a join request is approved only for an active linked employee; the bot
sends a join-request link after linking; a daily job removes deactivated staff who are still inside.
"""

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError, TelegramRetryAfter
from aiogram.methods import TelegramMethod
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bot import staff_channel as join_router
from app.models.auth import AuditLog, User
from app.models.clients import Client, ClientContact
from app.models.integrations import TelegramGroup
from app.models.leads import TelegramIdentity
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
        self.fail_for: dict[tuple[str, int], Exception] = {}  # (method, user id) -> error
        self.hang = False
        self.slept: list[float] = []

    async def __call__(
        self, method: TelegramMethod[Any], request_timeout: int | None = None
    ) -> Any:
        name = type(method).__name__
        data = method.model_dump(exclude_none=True)
        self.calls.append((name, data))
        if name in self.fail:
            raise self.fail[name]
        if (name, data.get("user_id", 0)) in self.fail_for:
            raise self.fail_for[(name, data["user_id"])]
        if self.hang and name in {"GetMe", "GetChatMember"}:
            await asyncio.sleep(30)
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

    async def no_sleep(_: float) -> None:
        bot.slept.append(_)

    return StaffChannelService(
        sessions, SettingsService(sessions, ttl_s=0), provider, sleep=no_sleep, probe_timeout_s=0.1
    )


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


async def test_outsider_is_skipped(
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


# --- review round ---------------------------------------------------------------------------


async def test_failed_unban_is_finished_on_retry(
    service: StaffChannelService, bot: FakeBot
) -> None:
    """Ban succeeded, unban failed: the retry sees `kicked` and unbans, without a second ban."""
    bot.members[(TEAM, TG)] = "member"
    method: Any = SimpleNamespace()
    bot.fail["UnbanChatMember"] = TelegramNetworkError(method=method, message="timeout")
    with pytest.raises(StaffChannelUnavailableError):
        await service.remove_member(1, TG)
    bot.fail.clear()
    bot.members[(TEAM, TG)] = "kicked"  # what Telegram says after the ban
    bot.calls.clear()
    await service.remove_member(1, TG)
    assert [n for n in bot.names() if n in {"BanChatMember", "UnbanChatMember"}] == [
        "UnbanChatMember"
    ]
    assert [d["only_if_banned"] for n, d in bot.calls if n == "UnbanChatMember"] == [True]


async def two_deactivated(sessions: async_sessionmaker[AsyncSession]) -> tuple[int, int]:
    first = await linked_user(sessions)
    second, _ = await make_user(sessions, "sanjar@railtech.uz", ["manager"])
    async with sessions() as session, session.begin():
        await session.execute(update(User).where(User.id == second.id).values(tg_user_id=TG + 1))
    for uid in (first, second.id):
        await UserService(sessions).update(Actor.system(), uid, UserPatch(is_active=False))
    return first, second.id


async def test_reconcile_survives_one_persons_error_and_honours_retry_after(
    sessions: async_sessionmaker[AsyncSession], service: StaffChannelService, bot: FakeBot
) -> None:
    await two_deactivated(sessions)
    method: Any = SimpleNamespace()
    bot.fail_for[("GetChatMember", TG)] = TelegramRetryAfter(
        method=method, message="flood", retry_after=7
    )
    bot.members[(TEAM, TG + 1)] = "member"
    assert await service.reconcile() == 1  # the second person was still checked and removed
    assert 7 in bot.slept  # Telegram's pause honoured
    assert {d["user_id"] for n, d in bot.calls if n == "BanChatMember"} == {TG + 1}


async def test_reconcile_skips_people_already_cleanly_removed(
    sessions: async_sessionmaker[AsyncSession], service: StaffChannelService, bot: FakeBot
) -> None:
    await two_deactivated(sessions)
    bot.members[(TEAM, TG)] = "member"
    assert await service.reconcile() == 1
    bot.calls.clear()
    assert await service.reconcile() == 0
    assert bot.calls == []  # both are recorded as clean: no Bot API calls


async def test_failed_removal_is_retried_by_the_next_reconcile(
    sessions: async_sessionmaker[AsyncSession], service: StaffChannelService, bot: FakeBot
) -> None:
    await two_deactivated(sessions)
    bot.members[(TEAM, TG)] = "member"
    method: Any = SimpleNamespace()
    bot.fail["BanChatMember"] = TelegramBadRequest(method=method, message="not enough rights")
    assert await service.reconcile() == 0
    bot.fail.clear()
    assert await service.reconcile() == 1  # not recorded as clean, so it is tried again


async def test_client_contact_stays_in_the_clients_group(
    sessions: async_sessionmaker[AsyncSession], service: StaffChannelService, bot: FakeBot
) -> None:
    """The same Telegram account is a contact of the client: only the team channel is cleaned."""
    async with sessions() as session, session.begin():
        client = Client(name="ООО Порядок")
        session.add(client)
        await session.flush()
        identity = TelegramIdentity(tg_user_id=TG, client_id=None)
        session.add(identity)
        await session.flush()
        session.add(
            ClientContact(
                client_id=client.id, full_name="Контакт", telegram_identity_id=identity.id
            )
        )
        group = await session.get(TelegramGroup, GROUP)
        assert group is not None
        group.client_id, group.status = client.id, "bound"
    inside(bot)
    result = await service.remove_member(1, TG)
    assert result.removed == 1
    assert [d["chat_id"] for n, d in bot.calls if n == "BanChatMember"] == [TEAM]


async def test_joined_is_journaled_only_after_telegram_accepted(
    sessions: async_sessionmaker[AsyncSession], service: StaffChannelService, bot: FakeBot
) -> None:
    await linked_user(sessions)
    method: Any = SimpleNamespace()
    bot.fail["ApproveChatJoinRequest"] = TelegramBadRequest(method=method, message="expired")
    request: Any = SimpleNamespace(chat=SimpleNamespace(id=TEAM), from_user=SimpleNamespace(id=TG))
    await join_router.on_join_request(request, bot, service)
    assert await journal(sessions, "user.team_channel_joined") == []


async def test_status_probe_does_not_hang_and_is_cached(
    sessions: async_sessionmaker[AsyncSession], service: StaffChannelService, bot: FakeBot
) -> None:
    bot.hang = True
    assert await service.can_invite() is None  # Telegram hangs: answered within the timeout
    bot.hang = False
    bot.bot_rights[TEAM] = SimpleNamespace(status="creator")
    assert await service.can_invite() is None  # the unknown answer is cached for minutes
    # connecting another channel invalidates the cache
    settings = SettingsService(sessions, ttl_s=0)
    current = (await settings.raw())["notifications"]
    await settings.update("notifications", {**current, "channel_id": GROUP}, None)
    bot.bot_rights[GROUP] = SimpleNamespace(status="creator")
    assert await service.can_invite() is True
    n = len(bot.calls)
    assert await service.can_invite() is True
    assert len(bot.calls) == n  # cached: no new Bot API calls


async def test_foreign_ban_is_not_lifted_by_reconcile(
    sessions: async_sessionmaker[AsyncSession], service: StaffChannelService, bot: FakeBot
) -> None:
    """A `kicked` status without our own unfinished ban (a group admin banned him) stays."""
    await two_deactivated(sessions)
    bot.members[(GROUP, TG)] = "kicked"
    await service.reconcile()
    assert [d for n, d in bot.calls if n in {"BanChatMember", "UnbanChatMember"}] == []
