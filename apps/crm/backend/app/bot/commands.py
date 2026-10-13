"""Меню команд клиентского бота (кнопка «Меню» в Telegram) — по статусу собеседника.

Глобальное меню (по языку Telegram) — вариант «prospect» для тех, кто ещё не писал.
Личное меню чата (`BotCommandScopeChat`) — по статусу из CRM (`domain/bot_menu.py`):
сразу после действия в CRM (задача `refresh_chat_menu` в очереди, `tasks/notify.py`) и лениво
при сообщении лида, если вариант или язык изменились.
"""

from typing import Protocol

import structlog
from aiogram import Bot
from aiogram.types import BotCommand, BotCommandScopeChat

from app.domain.bot_menu import MENUS, Command, MenuVariant
from app.schemas.settings import AppSettings, Language, LocalizedText
from app.services.client_bot import ChatStatus

logger = structlog.get_logger(__name__)
LANGUAGES: tuple[Language, ...] = ("ru", "uz", "en")


def commands_for(cfg: AppSettings, variant: MenuVariant, language: Language) -> list[BotCommand]:
    def label(command: Command) -> str:
        text: LocalizedText = getattr(cfg.texts, f"menu_{command}")
        return text.get(language)[:256]

    return [BotCommand(command=c, description=label(c)) for c in MENUS[variant]]


async def publish(bot: Bot, cfg: AppSettings | None = None) -> None:
    """Русское меню — по умолчанию, узбекское и английское — по языку клиента Telegram."""
    settings = cfg or AppSettings()
    try:
        for language in LANGUAGES:
            await bot.set_my_commands(
                commands_for(settings, "prospect", language),
                language_code=None if language == "ru" else language,
            )
    except Exception:
        logger.warning("bot_commands_not_published", exc_info=True)


async def publish_chat_menu(
    bot: Bot, chat_id: int, variant: MenuVariant, language: Language, cfg: AppSettings
) -> bool:
    """Личное меню чата; сбой Telegram (бот заблокирован, сеть) — в лог, не исключение."""
    try:
        await bot.set_my_commands(
            commands_for(cfg, variant, language), scope=BotCommandScopeChat(chat_id=chat_id)
        )
    except Exception:
        logger.warning("bot_chat_menu_not_published", chat_id=chat_id, exc_info=True)
        return False
    logger.info("bot_chat_menu_published", chat_id=chat_id, variant=variant)
    return True


class StatusSource(Protocol):
    async def status(self, tg_user_id: int) -> ChatStatus: ...


class SettingsSource(Protocol):
    async def get(self) -> AppSettings: ...


async def refresh_chat_menu(
    bot: Bot, client_bot: StatusSource, settings: SettingsSource, tg_user_id: int
) -> bool:
    """Меню личного чата по текущему статусу из БД (идемпотентно: тот же вариант — тот же вызов).

    Статус считается в момент выполнения, а не при постановке задачи: поздняя задача не вернёт
    устаревшее меню. Личный чат с ботом — `chat_id == tg_user_id`.
    """
    cfg = await settings.get()
    status = await client_bot.status(tg_user_id)
    return await publish_chat_menu(bot, tg_user_id, status.variant, status.language, cfg)


class ChatMenus:
    """Личное меню чата; последний опубликованный вариант кэшируется, чтобы не спамить API."""

    def __init__(self) -> None:
        self._published: dict[int, tuple[MenuVariant, Language]] = {}

    async def ensure(
        self, bot: Bot, chat_id: int, variant: MenuVariant, language: Language, cfg: AppSettings
    ) -> bool:
        if self._published.get(chat_id) == (variant, language):
            return False
        if not await publish_chat_menu(bot, chat_id, variant, language, cfg):
            return False
        self._published[chat_id] = (variant, language)
        return True
