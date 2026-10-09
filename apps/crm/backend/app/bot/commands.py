"""Меню команд клиентского бота (кнопка «Меню» в Telegram) на трёх языках."""

import structlog
from aiogram import Bot
from aiogram.types import BotCommand

logger = structlog.get_logger(__name__)

COMMANDS: dict[str, list[tuple[str, str]]] = {
    "ru": [
        ("start", "Начать"),
        ("human", "Позвать сотрудника"),
        ("lang", "Сменить язык"),
        ("help", "Что умеет бот"),
        ("delete", "Удалить переписку"),
    ],
    "uz": [
        ("start", "Boshlash"),
        ("human", "Xodimni chaqirish"),
        ("lang", "Tilni o'zgartirish"),
        ("help", "Bot nimalar qila oladi"),
        ("delete", "Yozishmani o'chirish"),
    ],
    "en": [
        ("start", "Start"),
        ("human", "Talk to a person"),
        ("lang", "Change language"),
        ("help", "What the bot can do"),
        ("delete", "Delete the conversation"),
    ],
}


async def publish(bot: Bot) -> None:
    """Русское меню — по умолчанию, узбекское и английское — по языку клиента Telegram."""
    try:
        for language, items in COMMANDS.items():
            commands = [BotCommand(command=name, description=text) for name, text in items]
            await bot.set_my_commands(
                commands, language_code=None if language == "ru" else language
            )
    except Exception:
        logger.warning("bot_commands_not_published", exc_info=True)
