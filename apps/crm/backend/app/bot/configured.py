"""Настроен ли клиентский Telegram-бот — единственная точка проверки.

Сейчас токен берётся из конфигурации (`.env`). Когда токен переедет в хранилище секретов
в БД, меняется только эта функция — чек-лист настройки и другие потребители не трогаются.
"""

from app.container import Container


async def bot_configured(container: Container) -> bool:
    return bool(container.settings.telegram_bot_token.get_secret_value())
