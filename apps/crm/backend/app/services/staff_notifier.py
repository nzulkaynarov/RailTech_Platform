"""Личные сообщения сотрудникам от бота (Q-010): алерты админам, сообщения лидов менеджеру.

Без кнопок (CLAUDE.md §11): только текст и ссылка на карточку в CRM. Бот может написать
человеку, только если тот нажал «Старт» в боте, — отказ Telegram логируется и не роняет вызов.
"""

from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any, Protocol

import structlog
from aiogram.exceptions import TelegramAPIError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.errors import ConflictError, Reason, ValidationFailedError
from app.domain.staff_notify import (
    Staff,
    alert_recipients,
    lead_dm_due,
    lead_dm_target,
    lead_dm_text,
)
from app.models.auth import Role, User, UserRole
from app.models.leads import Conversation, Lead, Message

logger = structlog.get_logger(__name__)
TEST_TEXT = "✅ Проверка доставки: личные уведомления CRM приходят сюда."


class Sender(Protocol):
    async def send_message(self, chat_id: int, text: str) -> Any: ...


class StaffNotifier:
    def __init__(self, sessions: async_sessionmaker[AsyncSession], bot: Sender | None) -> None:
        self._sessions = sessions
        self._bot = bot

    async def alert_admins(self, text: str, key: str) -> int:
        """Алерт в личку подписанным админам; возвращает число доставленных сообщений."""
        if self._bot is None:
            return 0
        async with self._sessions() as session:
            staff = await _staff(session)
        delivered = 0
        for chat_id in alert_recipients(staff):
            if await self._try_send(chat_id, text, key=key):
                delivered += 1
        return delivered

    async def lead_message(self, lead_id: int, now: datetime, window: timedelta, base: str) -> bool:
        """Новое сообщение лида → ответственному менеджеру, не чаще раза за `window`."""
        if self._bot is None:
            return False
        async with self._sessions() as session, session.begin():
            lead = await session.get(Lead, lead_id, with_for_update=True)
            if lead is None or lead.erased_at is not None or lead.assigned_user_id is None:
                return False
            if not lead_dm_due(lead.manager_notified_at, now, window):
                return False
            manager = await _staff(session, user_id=lead.assigned_user_id)
            target = lead_dm_target(lead.owner_mode, manager[0] if manager else None)
            if target is None:
                return False
            lead.manager_notified_at = now
            text = await _last_lead_text(session, lead_id)
            body = lead_dm_text(lead.display_name, text, base, lead_id)
        return await self._try_send(target, body, key="lead_message", lead_id=lead_id)

    async def test_message(self, user_id: int) -> None:
        """«Проверить доставку» из профиля; отказ Telegram → понятная ошибка с его текстом."""
        if self._bot is None:
            raise ConflictError("bot is not configured", reason=Reason.BOT_NOT_CONFIGURED)
        async with self._sessions() as session:
            tg_user_id = await session.scalar(select(User.tg_user_id).where(User.id == user_id))
        if tg_user_id is None:
            raise ValidationFailedError(
                "telegram is not linked", reason=Reason.TELEGRAM_NOT_LINKED, field="tg_user_id"
            )
        try:
            await self._bot.send_message(tg_user_id, TEST_TEXT)
        except TelegramAPIError as exc:
            logger.info("staff_test_dm_refused", user_id=user_id, error=exc.message)
            raise ConflictError(
                "telegram refused", reason=Reason.TELEGRAM_REFUSED, telegram_error=exc.message
            ) from exc

    async def _try_send(self, chat_id: int, text: str, **log: object) -> bool:
        if self._bot is None:
            return False
        try:
            await self._bot.send_message(chat_id, text)
        except TelegramAPIError as exc:
            # Человек не нажал «Старт» или заблокировал бота — не повод ронять монитор/задачу.
            logger.warning("staff_dm_failed", error=exc.message, **log)
            return False
        logger.info("staff_dm_sent", **log)
        return True


async def _staff(session: AsyncSession, user_id: int | None = None) -> list[Staff]:
    stmt = select(User)
    if user_id is not None:
        stmt = stmt.where(User.id == user_id)
    users: Sequence[User] = (await session.scalars(stmt.order_by(User.id))).all()
    roles_stmt = select(UserRole.user_id, Role.name).join(Role, Role.id == UserRole.role_id)
    roles: dict[int, list[str]] = {}
    for uid, name in (await session.execute(roles_stmt)).all():
        roles.setdefault(uid, []).append(name)
    return [
        Staff(
            user_id=u.id,
            roles=tuple(roles.get(u.id, ())),
            is_active=u.is_active,
            tg_user_id=u.tg_user_id,
            notify_system=u.notify_system,
            notify_leads=u.notify_leads,
        )
        for u in users
    ]


async def _last_lead_text(session: AsyncSession, lead_id: int) -> str:
    text = await session.scalar(
        select(Message.text)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(Conversation.lead_id == lead_id, Message.role == "lead")
        .order_by(Message.id.desc())
        .limit(1)
    )
    return text or ""
