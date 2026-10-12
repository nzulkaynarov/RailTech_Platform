"""Меню чата сразу после действия в CRM («Забрать», «Вернуть боту», «Сделать клиентом»), а не
со следующим сообщением лида (отложено из PR #21). Подставной aiogram Bot."""

from unittest.mock import AsyncMock

from aiogram.types import BotCommandScopeChat

from app.bot.commands import refresh_chat_menu
from app.schemas.settings import AppSettings
from app.services.client_bot import ChatStatus

CFG = AppSettings()
USER = 42


class Settings:
    async def get(self) -> AppSettings:
        return CFG


class Status:
    def __init__(self, variant: str, language: str = "ru") -> None:
        self.variant, self.language = variant, language

    async def status(self, tg_user_id: int) -> ChatStatus:
        return ChatStatus(self.variant, self.language, 1, None, False)  # type: ignore[arg-type]


def _published(bot: AsyncMock) -> list[str]:
    call = bot.set_my_commands.await_args
    assert call.kwargs["scope"] == BotCommandScopeChat(chat_id=USER)
    return [c.command for c in call.args[0]]


async def test_taken_lead_loses_human_command_immediately() -> None:
    bot = AsyncMock()
    assert await refresh_chat_menu(bot, Status("with_manager"), Settings(), USER)
    assert "human" not in _published(bot)


async def test_client_menu_after_make_customer_in_lead_language() -> None:
    bot = AsyncMock()
    assert await refresh_chat_menu(bot, Status("client", "uz"), Settings(), USER)
    assert _published(bot)[:3] == ["docs", "request", "status"]
    labels = [c.description for c in bot.set_my_commands.await_args.args[0]]
    assert CFG.texts.menu_docs.uz in labels


async def test_repeat_is_harmless_and_telegram_failure_is_logged_not_raised() -> None:
    bot = AsyncMock()
    assert await refresh_chat_menu(bot, Status("prospect"), Settings(), USER)
    assert await refresh_chat_menu(bot, Status("prospect"), Settings(), USER)  # идемпотентно
    bot.set_my_commands.side_effect = RuntimeError("Forbidden: bot was blocked by the user")
    assert not await refresh_chat_menu(bot, Status("prospect"), Settings(), USER)
