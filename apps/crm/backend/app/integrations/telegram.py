"""Telegram Bot API вне диалога: проверка токена (`getMe`) и выбор действующего токена.

Порядок выбора токена (аудит 2026-10-12 §3): секрет в БД («Подключения»), иначе
`TELEGRAM_BOT_TOKEN` из `.env`. Значение токена не логируется.
"""

from dataclasses import dataclass
from typing import Literal, Protocol

import structlog
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.exceptions import TelegramAPIError, TelegramNotFound, TelegramUnauthorizedError
from aiogram.utils.token import TokenValidationError

from app.config import Settings
from app.security.secrets_store import TELEGRAM_BOT_TOKEN, SecretsStore

logger = structlog.get_logger(__name__)

TokenSource = Literal["db", "env", "none"]


class InvalidBotTokenError(Exception):
    """Telegram не принял токен (формат или `getMe` → 401/404)."""


class TelegramUnavailableError(Exception):
    """Telegram не ответил (сеть, 5xx) — токен не проверен."""


@dataclass(frozen=True, slots=True)
class BotIdentity:
    id: int
    username: str


class TelegramProbe(Protocol):
    async def get_me(self, token: str) -> BotIdentity: ...


def make_bot(config: Settings, token: str, *, default: DefaultBotProperties | None = None) -> Bot:
    """`Bot` с адресом Bot API из `TELEGRAM_API_BASE_URL` (пусто — официальный сервер)."""
    base = config.telegram_api_base_url.strip()
    session = AiohttpSession(api=TelegramAPIServer.from_base(base)) if base else None
    return Bot(token, session=session, default=default)


class AiogramProbe:
    """`getMe` отдельным клиентом: токен проверяется до сохранения и до перезапуска бота."""

    def __init__(self, config: Settings | None = None) -> None:
        self._config = config

    async def get_me(self, token: str) -> BotIdentity:
        try:
            bot = make_bot(self._config, token) if self._config is not None else Bot(token)
        except TokenValidationError as exc:
            raise InvalidBotTokenError("malformed token") from exc
        try:
            me = await bot.get_me()
        except (TelegramUnauthorizedError, TelegramNotFound) as exc:
            raise InvalidBotTokenError(type(exc).__name__) from exc
        except TelegramAPIError as exc:
            raise TelegramUnavailableError(type(exc).__name__) from exc
        finally:
            await bot.session.close()
        return BotIdentity(id=me.id, username=me.username or "")


async def resolve_token(store: SecretsStore, config: Settings) -> tuple[str, TokenSource]:
    """Действующий токен и откуда он; сбой БД → токен из env (бот не должен падать)."""
    if store.enabled:
        try:
            stored = await store.get(TELEGRAM_BOT_TOKEN)
        except Exception:
            logger.warning("bot_token_db_unavailable", exc_info=True)
            stored = None
        if stored:
            return stored, "db"
    env = config.telegram_bot_token.get_secret_value()
    return (env, "env") if env else ("", "none")
