"""Сотрудник привязывает Telegram сам (W15-H6): одноразовый код, бот, отвязка.

«Привязать Telegram» в профиле выпускает код (в БД — хеш, срок 10 минут) и ссылку
`t.me/<бот>?start=staff_<код>`. Бот при `/start staff_<код>` вызывает `confirm`: код гасится, а
`users.tg_user_id` и `tg_username` записываются тому, кто выпустил код. Хранение то же, что при
привязке админом (`users.tg_user_id`, ею пользуется `StaffNotifier`). Новая ссылка отменяет прежнюю.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

import structlog
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain import staff_telegram as rules
from app.domain.errors import ConflictError, NotFoundError, Reason
from app.models.auth import StaffTelegramLink
from app.repositories import users as repo
from app.security import audit
from app.security.audit import Actor
from app.services.bot_state import BotStateService

logger = structlog.get_logger(__name__)
Status = Literal["linked", "invalid", "taken"]


@dataclass(frozen=True, slots=True)
class LinkTicket:
    url: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class LinkOutcome:
    status: Status
    language: str | None = None


def _utcnow() -> datetime:
    return datetime.now(UTC)


class StaffTelegramLinkService:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        bot_state: BotStateService,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._sessions = sessions
        self._bot_state = bot_state
        self._clock = clock

    async def begin(self, user_id: int) -> LinkTicket:
        """Новая ссылка привязки; прежние неиспользованные коды сотрудника гасятся."""
        snapshot = await self._bot_state.snapshot()
        if snapshot is None or not snapshot.alive or not snapshot.username:
            reason = Reason.BOT_NOT_RUNNING if snapshot is not None else Reason.BOT_NOT_CONFIGURED
            raise ConflictError("the bot is not available", reason=reason)
        code = rules.new_code()
        expires = self._clock() + rules.CODE_TTL
        async with self._sessions() as session, session.begin():
            if await repo.get(session, user_id) is None:
                raise NotFoundError("user not found")
            await session.execute(
                delete(StaffTelegramLink).where(
                    StaffTelegramLink.user_id == user_id, StaffTelegramLink.used_at.is_(None)
                )
            )
            session.add(
                StaffTelegramLink(
                    user_id=user_id, code_hash=rules.hash_code(code), expires_at=expires
                )
            )
        return LinkTicket(rules.deep_link(snapshot.username, code), expires)

    async def confirm(self, code: str, tg_user_id: int, tg_username: str | None) -> LinkOutcome:
        """`/start staff_<код>` в личном чате: привязать Telegram тому, кто выпустил код."""
        now = self._clock()
        async with self._sessions() as session, session.begin():
            link = await session.scalar(
                select(StaffTelegramLink)
                .where(StaffTelegramLink.code_hash == rules.hash_code(code))
                .with_for_update()
            )
            if link is None or link.used_at is not None or rules.is_expired(link.expires_at, now):
                logger.info("staff_telegram_code_rejected", known=link is not None)
                return LinkOutcome("invalid")
            user = await repo.get(session, link.user_id, for_update=True)
            if user is None or not user.is_active:
                return LinkOutcome("invalid")
            link.used_at = now
            language, user_id = user.language, user.id
            try:
                async with session.begin_nested():
                    user.tg_user_id = tg_user_id
                    user.tg_username = rules.clean_username(tg_username)
                    user.tg_dm_failed_at = None  # человек только что написал боту
                    await session.flush()
            except IntegrityError:
                return LinkOutcome("taken", language)
            await audit.record(
                session, Actor(user_id, "user"), "user.telegram_linked", "user", user_id,
                after={"tg_user_id": tg_user_id},
            )  # fmt: skip
            return LinkOutcome("linked", language)

    async def unlink(self, actor: Actor, user_id: int) -> None:
        async with self._sessions() as session, session.begin():
            user = await repo.get(session, user_id, for_update=True)
            if user is None:
                raise NotFoundError("user not found")
            await session.execute(
                delete(StaffTelegramLink).where(StaffTelegramLink.user_id == user_id)
            )
            if user.tg_user_id is not None:
                before = {"tg_user_id": user.tg_user_id}
                user.tg_user_id = None
                user.tg_username = None
                user.tg_dm_failed_at = None
                await audit.record(
                    session, actor, "user.telegram_unlinked", "user", user_id, before=before
                )
