"""Team channel and client groups as seen from staff membership (ОНБ-1.2).

The bot invites an employee with a join-request link (the request is approved only for an active
linked employee) and removes him from the team channel and from every client group with the
secretary when he is deactivated or unlinks Telegram: `banChatMember` + `unbanChatMember`, so he can
be re-invited later. All Bot API access goes through `current_bot`; a missing bot or a transient
Telegram failure raises, so the queue retries, and a daily reconciliation catches the rest.
"""

import asyncio
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

from app.models.auth import AuditLog, User
from app.models.clients import ClientContact
from app.models.integrations import TelegramGroup
from app.models.leads import TelegramIdentity
from app.repositories import users as users_repo
from app.security import audit
from app.security.audit import Actor
from app.services.settings import SettingsService

logger = structlog.get_logger(__name__)

INVITE_TTL = timedelta(days=7)
INVITE_NAME = "staff"
CHECKED = "user.telegram_chats_checked"
RECHECK_AFTER = timedelta(days=14)
PACE_S = 0.2  # between people in the daily job
MAX_PAUSE_S = 30.0  # longest honoured retry_after
PROBE_TIMEOUT_S = 2.0
INVITE_CACHE = timedelta(minutes=3)
_OUTSIDE = frozenset({"left", "kicked"})
_UNKNOWN_MEMBER = ("user not found", "participant_id_invalid")
Decision = Literal["approve", "decline", "ignore"]


class StaffChannelUnavailableError(Exception):
    """No bot or a transient Telegram failure: the task is retried."""

    def __init__(self, message: str, retry_after: float = 0.0) -> None:
        super().__init__(message)
        self.retry_after = retry_after


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
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        probe_timeout_s: float = PROBE_TIMEOUT_S,
    ) -> None:
        self._sessions = sessions
        self._settings = settings
        self._current_bot = current_bot
        self._clock = clock
        self._sleep = sleep
        self._probe_timeout_s = probe_timeout_s
        self._invite_cache: tuple[int, datetime, bool | None] | None = None

    async def _channel_id(self) -> int | None:
        return (await self._settings.get()).notifications.channel_id

    async def _chats(self) -> list[tuple[int, int | None]]:
        """The team channel and every client group the bot still sits in, with the bound client."""
        chats: list[tuple[int, int | None]] = []
        channel = await self._channel_id()
        if channel is not None:
            chats.append((channel, None))
        async with self._sessions() as session:
            rows = await session.execute(
                select(TelegramGroup.chat_id, TelegramGroup.client_id).where(
                    TelegramGroup.status != "removed"
                )
            )
            chats.extend((c, client) for c, client in rows if c != channel)
        return chats

    async def _is_client_contact(self, tg_user_id: int, client_id: int) -> bool:
        """A contact of the client the group is bound to must never be removed from that group."""
        async with self._sessions() as session:
            identity = await session.scalar(
                select(TelegramIdentity).where(TelegramIdentity.tg_user_id == tg_user_id)
            )
            if identity is None:
                return False
            if identity.client_id == client_id:
                return True
            contact = await session.scalar(
                select(ClientContact.id).where(
                    ClientContact.client_id == client_id,
                    ClientContact.telegram_identity_id == identity.id,
                )
            )
            return contact is not None

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
        removed, failed, transient, retry_after = 0, [], False, 0.0
        for chat_id, client_id in await self._chats():
            if client_id is not None and await self._is_client_contact(tg_user_id, client_id):
                continue
            try:
                if await self._kick(bot, chat_id, tg_user_id):
                    removed += 1
            except TelegramAPIError as exc:
                transient = transient or _is_transient(exc)
                if isinstance(exc, TelegramRetryAfter):
                    retry_after = max(retry_after, float(exc.retry_after))
                failed.append(chat_id)
                logger.warning(
                    "staff_chat_removal_failed", chat_id=chat_id, error=type(exc).__name__
                )
        if transient:
            raise StaffChannelUnavailableError("telegram is unavailable", retry_after)
        if (
            not failed or journal_failed
        ):  # a clean result is always recorded; failures once, not daily
            action = "user.telegram_chats_removed" if removed or failed else CHECKED
            async with self._sessions() as session, session.begin():
                await audit.record(
                    session, Actor.system(), action, "user", user_id,
                    after={"removed": removed, "failed": failed},
                )  # fmt: skip
        return RemovalResult(removed, failed)

    async def _kick(self, bot: Bot, chat_id: int, tg_user_id: int) -> bool:
        """True — he was inside and is removed; False — he was not a member.

        Idempotent: a `kicked` status (a ban whose unban failed earlier) is unbanned again.
        """
        try:
            member = await bot.get_chat_member(chat_id, tg_user_id)
        except TelegramBadRequest as exc:
            if any(marker in str(exc).lower() for marker in _UNKNOWN_MEMBER):
                return False
            raise
        if member.status == "kicked":
            await bot.unban_chat_member(chat_id, tg_user_id, only_if_banned=True)
            return False
        if member.status in _OUTSIDE:
            return False
        await bot.ban_chat_member(chat_id, tg_user_id)
        await bot.unban_chat_member(chat_id, tg_user_id, only_if_banned=True)
        return True

    async def _recently_clean(self) -> set[int]:
        """Users whose last check or removal in the past 14 days left no failed chat."""
        since = self._clock() - RECHECK_AFTER
        async with self._sessions() as session:
            rows = await session.execute(
                select(AuditLog.entity_id, AuditLog.after)
                .where(
                    AuditLog.action.in_(("user.telegram_chats_removed", CHECKED)),
                    AuditLog.created_at >= since,
                )
                .order_by(AuditLog.id)
            )
        latest: dict[str, bool] = {}
        for entity_id, after in rows:
            if entity_id is not None:
                latest[entity_id] = not (after or {}).get("failed")
        return {int(k) for k, clean in latest.items() if clean}

    async def reconcile(self) -> int:
        """Daily: deactivated staff with a known Telegram still inside; returns kicked count.

        One person's error never stops the loop; Telegram's `retry_after` is honoured and calls are
        paced; people cleanly removed or checked in the last 14 days are skipped.
        """
        done = await self._recently_clean()
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
            if tg_user_id is None or user_id in done:
                continue
            try:
                kicked += (
                    await self.remove_member(user_id, tg_user_id, journal_failed=False)
                ).removed
            except StaffChannelUnavailableError as exc:
                logger.warning("staff_reconcile_person_failed", user_id=user_id)
                await self._sleep(min(exc.retry_after, MAX_PAUSE_S))
            await self._sleep(PACE_S)
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
        return "approve"

    async def record_joined(self, tg_user_id: int) -> None:
        """Journal the join after Telegram accepted the approval."""
        async with self._sessions() as session, session.begin():
            user = await users_repo.by_tg_user_id(session, tg_user_id)
            if user is not None:
                await audit.record(
                    session, Actor.system(), "user.team_channel_joined", "user", user.id
                )

    async def can_invite(self) -> bool | None:
        """Does the bot hold the «invite users» right in the team channel; None — unknown.

        Short timeout (a hanging Telegram must not hang the status), cached for minutes; the cache
        is keyed by the channel, so connecting another channel invalidates it.
        """
        channel = await self._channel_id()
        bot = await self._current_bot()
        if channel is None or bot is None:
            return None
        now = self._clock()
        cached = self._invite_cache
        if cached is not None and cached[0] == channel and now - cached[1] < INVITE_CACHE:
            return cached[2]
        try:
            value = await asyncio.wait_for(self._probe_invite(bot, channel), self._probe_timeout_s)
        except (TelegramAPIError, TimeoutError):
            value = None
        self._invite_cache = (channel, now, value)
        return value

    @staticmethod
    async def _probe_invite(bot: Bot, channel: int) -> bool:
        me = await bot.me()
        member = await bot.get_chat_member(channel, me.id)
        if member.status == "creator":
            return True
        return member.status == "administrator" and bool(getattr(member, "can_invite_users", False))
