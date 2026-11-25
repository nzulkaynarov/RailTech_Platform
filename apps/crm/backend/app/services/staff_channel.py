"""Team channel and client groups as seen from staff membership (ОНБ-1.2).

The bot invites an employee with a join-request link (the request is approved only for an active
linked employee) and removes him from the team channel and from every client group with the
secretary when he is deactivated or unlinks Telegram: `banChatMember` + `unbanChatMember`, so he can
be re-invited later. All Bot API access goes through `current_bot`; a missing bot or a transient
Telegram failure raises, so the queue retries, and a daily reconciliation catches the rest.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Literal

import structlog
from aiogram import Bot
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramNetworkError,
    TelegramRetryAfter,
    TelegramServerError,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.auth import User
from app.models.integrations import TelegramGroup
from app.repositories import users as users_repo
from app.security import audit
from app.security.audit import Actor
from app.services.settings import SettingsService

logger = structlog.get_logger(__name__)

INVITE_TTL = timedelta(days=7)
INVITE_NAME = "staff"
_OUTSIDE = frozenset({"left", "kicked"})
_UNKNOWN_MEMBER = ("user not found", "participant_id_invalid")
Decision = Literal["approve", "decline", "ignore"]


class StaffChannelUnavailableError(Exception):
    """No bot or a transient Telegram failure: the task is retried."""


@dataclass(frozen=True, slots=True)
class RemovalResult:
    removed: int = 0
    failed: list[int] = field(default_factory=list)  # chats where the bot could not remove him


def _is_transient(exc: TelegramAPIError) -> bool:
    return isinstance(exc, TelegramRetryAfter | TelegramNetworkError | TelegramServerError)


class StaffChannelService:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        settings: SettingsService,
        current_bot: Callable[[], Awaitable[Bot | None]],
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._sessions = sessions
        self._settings = settings
        self._current_bot = current_bot
        self._clock = clock

    async def _channel_id(self) -> int | None:
        return (await self._settings.get()).notifications.channel_id

    async def _chats(self) -> list[int]:
        """The team channel and every client group the bot still sits in."""
        chats: list[int] = []
        channel = await self._channel_id()
        if channel is not None:
            chats.append(channel)
        async with self._sessions() as session:
            groups = await session.scalars(
                select(TelegramGroup.chat_id).where(TelegramGroup.status != "removed")
            )
            chats.extend(c for c in groups if c not in chats)
        return chats

    async def remove_member(
        self, user_id: int, tg_user_id: int, *, journal_failed: bool = True
    ) -> RemovalResult:
        """Kick `tg_user_id` from the team channel and client groups unless he is staff again."""
        async with self._sessions() as session:
            current = await users_repo.by_tg_user_id(session, tg_user_id)
        if current is not None:  # reactivated or relinked before the task ran
            return RemovalResult()
        bot = await self._current_bot()
        if bot is None:
            raise StaffChannelUnavailableError("no bot")
        removed, failed, transient = 0, [], False
        for chat_id in await self._chats():
            try:
                if await self._kick(bot, chat_id, tg_user_id):
                    removed += 1
            except TelegramAPIError as exc:
                transient = transient or _is_transient(exc)
                failed.append(chat_id)
                logger.warning(
                    "staff_chat_removal_failed", chat_id=chat_id, error=type(exc).__name__
                )
        if transient:
            raise StaffChannelUnavailableError("telegram is unavailable")
        if removed or (failed and journal_failed):
            async with self._sessions() as session, session.begin():
                await audit.record(
                    session, Actor.system(), "user.telegram_chats_removed", "user", user_id,
                    after={"removed": removed, "failed": failed},
                )  # fmt: skip
        return RemovalResult(removed, failed)

    async def _kick(self, bot: Bot, chat_id: int, tg_user_id: int) -> bool:
        """True — he was inside and is removed; False — he was not a member."""
        try:
            member = await bot.get_chat_member(chat_id, tg_user_id)
        except TelegramBadRequest as exc:
            if any(marker in str(exc).lower() for marker in _UNKNOWN_MEMBER):
                return False
            raise
        if member.status in _OUTSIDE:
            return False
        await bot.ban_chat_member(chat_id, tg_user_id)
        await bot.unban_chat_member(chat_id, tg_user_id, only_if_banned=True)
        return True

    async def reconcile(self) -> int:
        """Daily: deactivated staff with a known Telegram still inside; returns kicked count."""
        async with self._sessions() as session:
            rows = (
                await session.execute(
                    select(User.id, User.tg_user_id).where(
                        User.is_active.is_(False), User.tg_user_id.is_not(None)
                    )
                )
            ).all()
        kicked = 0
        for user_id, tg_user_id in rows:
            if tg_user_id is None:
                continue
            kicked += (await self.remove_member(user_id, tg_user_id, journal_failed=False)).removed
        return kicked

    async def invite_url(self, tg_user_id: int) -> str | None:
        """Join-request link to the team channel; None — no channel, or he is already inside."""
        channel = await self._channel_id()
        bot = await self._current_bot()
        if channel is None or bot is None:
            return None
        try:
            member = await bot.get_chat_member(channel, tg_user_id)
            if member.status not in _OUTSIDE:
                return None
        except TelegramAPIError:
            pass  # unknown to the channel: invite as for an outsider
        try:
            link = await bot.create_chat_invite_link(
                channel,
                name=INVITE_NAME,
                expire_date=self._clock() + INVITE_TTL,
                creates_join_request=True,
            )
        except TelegramAPIError as exc:
            logger.warning("staff_invite_failed", error=type(exc).__name__)
            return None
        return link.invite_link

    async def decide_join(self, chat_id: int, tg_user_id: int) -> Decision:
        """Approve an active linked employee, decline anyone else; other chats are not ours."""
        if chat_id != await self._channel_id():
            return "ignore"
        async with self._sessions() as session, session.begin():
            user = await users_repo.by_tg_user_id(session, tg_user_id)
            if user is None:
                await audit.record(
                    session, Actor.system(), "team_channel.join_declined", "telegram_chat",
                    chat_id, after={"tg_user_id": tg_user_id},
                )  # fmt: skip
                return "decline"
            await audit.record(session, Actor.system(), "user.team_channel_joined", "user", user.id)
        return "approve"

    async def can_invite(self) -> bool | None:
        """Does the bot hold the «invite users» right in the team channel; None — unknown."""
        channel = await self._channel_id()
        bot = await self._current_bot()
        if channel is None or bot is None:
            return None
        try:
            me = await bot.me()
            member = await bot.get_chat_member(channel, me.id)
        except TelegramAPIError:
            return None
        if member.status == "creator":
            return True
        return member.status == "administrator" and bool(getattr(member, "can_invite_users", False))
