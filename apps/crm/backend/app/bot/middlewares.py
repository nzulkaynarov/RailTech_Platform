"""Middleware клиентского бота: идемпотентность и rate-limit (SPEC §9.2, §11)."""

import time
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable
from typing import Any

import structlog
from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject, Update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bot.attachments import attachment_meta, media_of
from app.domain.language import Language
from app.models.leads import TgUpdate
from app.schemas.settings import AppSettings
from app.services.conversation_types import Incoming

logger = structlog.get_logger(__name__)

Handler = Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]]

SettingsProvider = Callable[[], Awaitable[AppSettings]]


class IdempotencyMiddleware(BaseMiddleware):
    """Каждый `update_id` обрабатывается один раз (таблица `tg_updates`)."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def __call__(self, handler: Handler, event: TelegramObject, data: dict[str, Any]) -> Any:
        if not isinstance(event, Update):
            return await handler(event, data)
        async with self._sessions() as session, session.begin():
            stmt = insert(TgUpdate).values(update_id=event.update_id).on_conflict_do_nothing()
            inserted = (await session.execute(stmt.returning(TgUpdate.update_id))).first()
        if inserted is None:
            logger.info("tg_update_duplicate_skipped", update_id=event.update_id)
            return None
        return await handler(event, data)


class RateLimitMiddleware(BaseMiddleware):
    """Не больше `bot.rate_limit_per_minute` сообщений в минуту на пользователя.

    Предупреждение отправляется не чаще раза в окно.
    """

    def __init__(
        self,
        settings: SettingsProvider,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._settings = settings
        self._clock = clock
        self._hits: defaultdict[int, deque[float]] = defaultdict(deque)
        self._warned: dict[int, float] = {}

    async def __call__(self, handler: Handler, event: TelegramObject, data: dict[str, Any]) -> Any:
        if not isinstance(event, Message) or event.from_user is None:
            return await handler(event, data)
        user_id = event.from_user.id
        now = self._clock()
        hits = self._hits[user_id]
        while hits and now - hits[0] > 60:
            hits.popleft()
        cfg = await self._settings()
        if len(hits) >= cfg.bot.rate_limit_per_minute:
            if now - self._warned.get(user_id, -120.0) > 60:
                self._warned[user_id] = now
                await event.answer(cfg.texts.rate_limited.get(await _language(event, data)))
            logger.info("tg_rate_limited", tg_user_id=user_id)
            await _record_silenced(event, data)
            return None
        hits.append(now)
        return await handler(event, data)


async def _record_silenced(
    event: Message, data: dict[str, Any], meta: dict[str, Any] | None = None
) -> None:
    """Бот промолчал, но сообщение лида сохраняется: менеджер увидит его в CRM."""
    conversation = data.get("conversation")
    user = event.from_user
    if conversation is None or user is None:
        return
    text = (event.text or event.caption or "")[:4000]
    media = media_of(event)
    attachments = [attachment_meta(media) | {"stored": False}] if media else []
    inc = Incoming(
        tg_user_id=user.id,
        chat_id=event.chat.id,
        text=text,
        message_id=event.message_id,
        attachments=attachments,
    )
    try:
        await conversation.record_lead_message(inc, meta=meta or {"rate_limited": True})
    except Exception:
        logger.exception("tg_rate_limited_record_failed", tg_user_id=user.id)


async def _language(event: Message, data: dict[str, Any]) -> Language:
    """Язык лида из CRM (а не настроек Telegram), если сервис диалога доступен."""
    conversation = data.get("conversation")
    user = event.from_user
    if conversation is not None and user is not None:
        language: Language = await conversation.language_of(user.id)
        return language
    code = ((user.language_code if user else None) or "ru")[:2]
    languages: dict[str, Language] = {"uz": "uz", "en": "en"}
    return languages.get(code, "ru")
