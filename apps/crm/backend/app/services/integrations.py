"""«Подключения» (аудит 2026-10-12 §3, шаг 2): токен бота и канал команды из интерфейса админа.

Безопасность: токен только на запись — в ответы и логи уходят `configured` и `last4`;
смена токена требует пароль админа и проверку `getMe` до сохранения; аудит без значения.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

import structlog
from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.errors import (
    ConflictError,
    NotFoundError,
    Reason,
    UpstreamUnavailableError,
    ValidationFailedError,
)
from app.integrations.telegram import (
    BotIdentity,
    InvalidBotTokenError,
    TelegramProbe,
    TelegramUnavailableError,
    TokenSource,
)
from app.repositories import telegram_chats
from app.repositories import users as users_repo
from app.security import audit
from app.security.passwords import verify_password
from app.security.principal import Principal
from app.security.secrets_store import TELEGRAM_BOT_TOKEN, SecretsStore, last4
from app.services import channel_texts
from app.services.settings import SettingsService

logger = structlog.get_logger(__name__)


class BotControl(Protocol):
    """Что сервису нужно от супервизора бота (`app/bot/supervisor.py`)."""

    @property
    def mode(self) -> str: ...
    @property
    def running(self) -> bool: ...
    @property
    def source(self) -> TokenSource: ...
    @property
    def username(self) -> str | None: ...
    @property
    def last_error(self) -> str | None: ...
    async def restart(self) -> None: ...


@dataclass(frozen=True, slots=True)
class TelegramStatus:
    configured: bool
    source: TokenSource
    last4: str | None
    updated_at: datetime | None
    username: str | None
    mode: str
    running: bool
    last_error: str | None
    secrets_enabled: bool
    channel_id: int | None
    channel_title: str | None


@dataclass(frozen=True, slots=True)
class ChatCandidate:
    chat_id: int
    title: str
    chat_type: str
    detected_at: datetime


class TelegramIntegrationService:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        settings: SettingsService,
        store: SecretsStore,
        probe: TelegramProbe,
        bot_control: BotControl | None,
        current_bot: Callable[[], Awaitable[Bot | None]],
        *,
        mode: str,
    ) -> None:
        self._sessions = sessions
        self._settings = settings
        self._store = store
        self._probe = probe
        self._bot = bot_control
        self._current_bot = current_bot
        self._mode = mode

    async def status(self) -> TelegramStatus:
        stored = await self._store.status(TELEGRAM_BOT_TOKEN) if self._store.enabled else None
        channel_id = (await self._settings.get()).notifications.channel_id
        title = None
        if channel_id is not None:
            async with self._sessions() as session:
                row = await telegram_chats.get(session, channel_id)
            title = row.title if row is not None else None
        bot = self._bot
        source: TokenSource = bot.source if bot is not None else "none"
        return TelegramStatus(
            configured=source != "none" or stored is not None,
            source=source if bot is not None else ("db" if stored else "none"),
            last4=stored.last4 if stored else None,
            updated_at=stored.updated_at if stored else None,
            username=bot.username if bot is not None else None,
            mode=bot.mode if bot is not None else self._mode,
            running=bot.running if bot is not None else False,
            last_error=bot.last_error if bot is not None else None,
            secrets_enabled=self._store.enabled,
            channel_id=channel_id,
            channel_title=title,
        )

    async def save_token(self, who: Principal, token: str, password: str) -> BotIdentity:
        """Пароль → `getMe` → запись + аудит → перезапуск бота. Неверный токен не сохраняется."""
        if not self._store.enabled:
            raise ConflictError("SECRETS_KEY is not set", reason=Reason.SECRETS_KEY_MISSING)
        await self._reauth(who.user_id, password)
        identity = await self._check(token.strip())
        async with self._sessions() as session, session.begin():
            await self._store.put(session, TELEGRAM_BOT_TOKEN, token.strip(), who.user_id)
            await audit.record(
                session,
                who.actor,
                "integrations.telegram_token",
                "integration_secret",
                TELEGRAM_BOT_TOKEN,
                after={"last4": last4(token.strip()), "bot_username": identity.username},
            )
        logger.info("bot_token_saved", user_id=who.user_id, bot_username=identity.username)
        if self._bot is not None:
            await self._bot.restart()
        return identity

    async def _reauth(self, user_id: int, password: str) -> None:
        async with self._sessions() as session:
            user = await users_repo.get(session, user_id)
        if user is None or not verify_password(user.password_hash, password):
            raise ValidationFailedError(
                "password is wrong", reason=Reason.WRONG_PASSWORD, field="password"
            )

    async def _check(self, token: str) -> BotIdentity:
        try:
            return await self._probe.get_me(token)
        except InvalidBotTokenError as exc:
            raise ValidationFailedError(
                "telegram rejected the token", reason=Reason.INVALID_BOT_TOKEN, field="token"
            ) from exc
        except TelegramUnavailableError as exc:
            raise UpstreamUnavailableError(
                "telegram is unavailable", reason=Reason.TELEGRAM_UNAVAILABLE
            ) from exc

    async def candidates(self) -> list[ChatCandidate]:
        async with self._sessions() as session:
            rows = await telegram_chats.list_all(session)
        return [ChatCandidate(r.chat_id, r.title, r.chat_type, r.detected_at) for r in rows]

    async def connect_channel(self, who: Principal, chat_id: int) -> None:
        async with self._sessions() as session:
            row = await telegram_chats.get(session, chat_id)
        if row is None:
            raise NotFoundError("chat was not detected")
        current = (await self._settings.raw())["notifications"]
        await self._settings.update(
            "notifications", {**current, "channel_id": chat_id}, who.user_id, who.actor
        )

    async def send_test(self) -> None:
        channel_id = (await self._settings.get()).notifications.channel_id
        if channel_id is None:
            raise ConflictError("no team channel", reason=Reason.CHANNEL_NOT_CONFIGURED)
        bot = await self._current_bot()
        if bot is None:
            raise ConflictError("no bot token", reason=Reason.BOT_NOT_RUNNING)
        try:
            await bot.send_message(channel_id, channel_texts.CHANNEL_TEST)
        except TelegramAPIError as exc:
            logger.warning("channel_test_failed", chat_id=channel_id, error=type(exc).__name__)
            raise UpstreamUnavailableError(
                "telegram refused the message", reason=Reason.CHANNEL_SEND_FAILED
            ) from exc
