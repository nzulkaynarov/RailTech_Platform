"""Сообщения Telegram по событиям ERP: считаются в транзакции обработки, уходят после коммита.

Обработчик события (`ErpEventsService.apply`) кладёт сообщения в `erp_event_notices` той же
транзакцией, что и изменения зеркала. Отправка — отдельным шагом после коммита (`deliver`, его
вызывает `CrmBus.process_inbox`), поэтому:
* откат транзакции или автоповтор обработчика сообщений не задваивает (строка либо есть, либо нет);
* падение воркера между коммитом и отправкой сообщение не теряет — его досылает сборщик (`sweep`,
  раз в минуту) не позже суток: устаревшее «счёт выставлен» вредит;
* каждый адресат получает сообщение один раз даже при частичном сбое: ушедшие записываются в `sent`.
Постоянные отказы Telegram (бот заблокирован, чат не найден) повторов не вызывают; сетевые сбои,
лимиты и 5xx — повторяются сборщиком.
"""

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from aiogram import Bot
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramNetworkError,
    TelegramRetryAfter,
    TelegramServerError,
)
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.models.auth import User
from app.models.integrations import ErpEventNotice
from app.models.leads import TelegramIdentity

logger = structlog.get_logger(__name__)

#: Неотправленное сообщение старше этого сборщик не досылает.
UNSENT_MAX_AGE = timedelta(hours=24)
#: Сообщение моложе этого сборщик не трогает: его отправит задача после обработки события.
SWEEP_AFTER = timedelta(seconds=60)
#: Аренда строки на время отправки: дольше таймаута Telegram, короче интервала сборщика.
LEASE = timedelta(seconds=45)
SWEEP_LIMIT = 100
SEND_TIMEOUT_S = 10

BotProvider = Callable[[], Awaitable[Bot | None]]


@dataclass(frozen=True, slots=True)
class _Send:
    key: str
    chat_id: int
    text: str
    markup: InlineKeyboardMarkup | None


def _transient(exc: Exception) -> bool:
    """Сбой, который может пройти сам: сеть, лимит, 5xx Telegram. Остальное — отказ адресату."""
    return isinstance(
        exc,
        TelegramNetworkError | TelegramRetryAfter | TelegramServerError | OSError | TimeoutError,
    )


def _markup(buttons: list[list[str]]) -> InlineKeyboardMarkup | None:
    if not buttons:
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=label, url=url)] for label, url in buttons]
    )


class ErpEventNotices:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        bot_provider: BotProvider,
        config: Settings,
    ) -> None:
        self._sessions = sessions
        self._bot_provider = bot_provider
        self._config = config

    @staticmethod
    def add(session: AsyncSession, event_id: str, items: list[dict[str, Any]]) -> None:
        """Записать сообщения события в транзакции обработки (повтор по тому же id заменяет их)."""
        session.add(ErpEventNotice(event_id=uuid.UUID(event_id), items=items, sent=[]))

    async def deliver(self, event_id: str) -> int:
        """Отправить сообщения события после коммита; возвращает число отправленных."""
        key = uuid.UUID(event_id)
        sends = await self._claim(key)
        if not sends:
            return 0
        bot = await self._bot_provider()
        if bot is None:
            await self._release(key, [], retry=True)
            return 0
        done: list[str] = []
        retry = False
        for send in sends:
            try:
                await bot.send_message(
                    chat_id=send.chat_id,
                    text=send.text,
                    reply_markup=send.markup,
                    request_timeout=SEND_TIMEOUT_S,
                )
            except (TelegramAPIError, OSError, TimeoutError, ValueError) as exc:
                logger.warning(
                    "erp_event_telegram_failed",
                    event_id=event_id,
                    tg_user_id=send.chat_id,
                    error=type(exc).__name__,
                    transient=_transient(exc),
                )
                if _transient(exc):
                    retry = True
                    continue
            done.append(send.key)
        await self._release(key, done, retry=retry)
        return len(done)

    async def sweep(self, limit: int = SWEEP_LIMIT) -> int:
        """Досылает сообщения, которые не ушли (воркер упал, бота не было, сеть); раз в минуту.

        Сообщения старше суток закрываются без отправки. Возвращает число отправленных.
        """
        now = datetime.now(UTC)
        async with self._sessions() as session, session.begin():
            await session.execute(
                update(ErpEventNotice)
                .where(
                    ErpEventNotice.notified_at.is_(None),
                    ErpEventNotice.created_at < now - UNSENT_MAX_AGE,
                )
                .values(notified_at=now)
            )
            pending = list(
                await session.scalars(
                    select(ErpEventNotice.event_id)
                    .where(
                        ErpEventNotice.notified_at.is_(None),
                        ErpEventNotice.created_at < now - SWEEP_AFTER,
                    )
                    .order_by(ErpEventNotice.created_at)
                    .limit(limit)
                )
            )
        sent = 0
        for event_id in pending:
            sent += await self.deliver(str(event_id))
        if sent:
            logger.warning("erp_event_notices_swept", notified=sent)
        return sent

    async def _claim(self, key: uuid.UUID) -> list[_Send]:
        """Взять строку в аренду и посчитать, что ещё не отправлено. Пусто — слать нечего."""
        now = datetime.now(UTC)
        async with self._sessions() as session, session.begin():
            row = await session.get(ErpEventNotice, key, with_for_update=True)
            if row is None or row.notified_at is not None:
                return []
            if row.lease_until is not None and row.lease_until > now:
                return []  # сообщение шлёт параллельный воркер
            if self._config.telegram_dry_run or await self._bot_provider() is None:
                return []  # бота нет или он выключен: сообщение дождётся сборщика (до суток)
            sends = await self._targets(session, row)
            if not sends:
                row.notified_at = now
                return []
            row.lease_until = now + LEASE
            return sends

    async def _release(self, key: uuid.UUID, done: list[str], *, retry: bool) -> None:
        async with self._sessions() as session, session.begin():
            row = await session.get(ErpEventNotice, key, with_for_update=True)
            if row is None:
                return
            row.sent = [*row.sent, *done]
            row.lease_until = None
            if not retry:
                row.notified_at = datetime.now(UTC)

    async def _targets(self, session: AsyncSession, row: ErpEventNotice) -> list[_Send]:
        already = set(row.sent)
        sends: list[_Send] = []
        for index, item in enumerate(row.items):
            chats: list[int] = []
            markup: InlineKeyboardMarkup | None = None
            if item.get("kind") == "client":
                markup = _markup(item.get("buttons") or [])
                chats = list(
                    (
                        await session.scalars(
                            select(TelegramIdentity.tg_user_id).where(
                                TelegramIdentity.client_id == item["client_id"],
                                TelegramIdentity.is_blocked.is_(False),
                            )
                        )
                    ).all()
                )
            elif item.get("kind") == "staff":
                tg_user_id = await session.scalar(
                    select(User.tg_user_id).where(
                        User.id == item["user_id"], User.is_active.is_(True)
                    )
                )
                chats = [tg_user_id] if tg_user_id else []
            for chat_id in chats:
                key = f"{index}:{chat_id}"
                if key not in already:
                    sends.append(_Send(key, chat_id, item["text"], markup))
        return sends
