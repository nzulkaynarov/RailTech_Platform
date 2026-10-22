"""«Подключения» (аудит 2026-10-12 §3, шаг 2): токен бота и канал команды из интерфейса админа.

Безопасность: токен только на запись — в ответы и логи уходят `configured` и `last4`;
смена токена требует пароль админа и проверку `getMe` до сохранения; аудит без значения.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

import structlog
from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bot.profile import ProfilePublish, publish_profile
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
from app.schemas.settings_profile import BotProfileSettings
from app.security import audit, reauth
from app.security.principal import Principal
from app.security.secrets_store import TELEGRAM_BOT_TOKEN, SecretsStore, last4
from app.services import channel_texts
from app.services.bot_state import BotSnapshot
from app.services.settings import SettingsService

logger = structlog.get_logger(__name__)


class BotLink(Protocol):
    """Что сервису нужно от `crm-bot`: он в другом процессе, связь — через БД (`bot_state`)."""

    async def snapshot(self) -> BotSnapshot | None: ...
    async def request_restart(self, session: AsyncSession) -> datetime: ...
    async def wait_applied(self, requested_at: datetime, timeout_s: float) -> bool: ...
    async def record_profile(self, result: ProfilePublish) -> None: ...


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


def _bot_error(bot: BotSnapshot | None) -> str | None:
    """Причина «бот не работает» для админа: нет пульса `crm-bot` — отдельная причина."""
    if bot is None:
        return "bot_process_never_started"
    if not bot.alive:
        return "bot_process_down"
    return bot.last_error


class TelegramIntegrationService:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        settings: SettingsService,
        store: SecretsStore,
        probe: TelegramProbe,
        bot_link: BotLink,
        current_bot: Callable[[], Awaitable[Bot | None]],
        *,
        mode: str,
        restart_wait_s: float = 10.0,
        lockout: reauth.LockoutPolicy | None = None,
    ) -> None:
        self._lockout = lockout or reauth.LockoutPolicy()
        self._sessions = sessions
        self._settings = settings
        self._store = store
        self._probe = probe
        self._bot = bot_link
        self._restart_wait_s = restart_wait_s
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
        bot = await self._bot.snapshot()
        reported: TokenSource = "none"
        if bot is not None and bot.alive and bot.source in ("db", "env"):
            reported = bot.source  # type: ignore[assignment]
        return TelegramStatus(
            configured=reported != "none" or stored is not None,
            source=reported if reported != "none" else ("db" if stored else "none"),
            last4=stored.last4 if stored else None,
            updated_at=stored.updated_at if stored else None,
            username=bot.username if bot is not None else None,
            mode=self._mode,
            running=bot.running if bot is not None else False,
            last_error=_bot_error(bot),
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
            requested_at = await self._bot.request_restart(session)
            await audit.record(
                session,
                who.actor,
                "integrations.telegram_token",
                "integration_secret",
                TELEGRAM_BOT_TOKEN,
                after={"last4": last4(token.strip()), "bot_username": identity.username},
            )
        logger.info("bot_token_saved", user_id=who.user_id, bot_username=identity.username)
        # Бот живёт в `crm-bot`: он замечает запрос в БД и перезапускается сам (S0-4). Ждём немного,
        # чтобы ответ уже показывал новый статус; не успел — токен сохранён, статус обновится.
        applied = await self._bot.wait_applied(requested_at, self._restart_wait_s)
        if not applied:
            logger.warning("bot_restart_not_confirmed", wait_s=self._restart_wait_s)
        return identity

    async def _reauth(self, user_id: int, password: str) -> None:
        """Пароль с тем же lockout, что у входа (аудит P0-4); счётчик коммитится до ошибки."""
        async with self._sessions() as session, session.begin():
            user = await users_repo.get(session, user_id, for_update=True)
            if user is None:
                raise ValidationFailedError(
                    "password is wrong", reason=Reason.WRONG_PASSWORD, field="password"
                )
            failure = reauth.check(user, password, datetime.now(UTC), self._lockout)
        if failure is not None:
            raise failure

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

    async def profile(self) -> tuple[BotProfileSettings, ProfilePublish | None]:
        """Профиль бота из настроек и итог последней публикации в Telegram."""
        current = (await self._settings.get()).bot_profile
        snapshot = await self._bot.snapshot()
        return current, snapshot.profile if snapshot is not None else None

    async def save_profile(
        self, who: Principal, profile: BotProfileSettings
    ) -> tuple[BotProfileSettings, ProfilePublish | None]:
        """Сохранить (аудит `settings.update`) и сразу опубликовать отличия в Telegram."""
        await self._settings.update(
            "bot_profile", profile.model_dump(mode="json"), who.user_id, who.actor
        )
        bot = await self._current_bot()
        if bot is None:
            result = ProfilePublish(False, datetime.now(UTC), error="bot_not_running")
        else:
            result = await publish_profile(bot, profile)
        await self._bot.record_profile(result)
        return profile, result

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
