"""Настроен ли клиентский Telegram-бот — единственная точка проверки (чек-лист настройки и др.).

Токен — из хранилища секретов в БД, иначе из `.env` (ADR-0018, `resolve_token`).
"""

from app.container import Container
from app.integrations.telegram import resolve_token


async def bot_configured(container: Container) -> bool:
    token, _source = await resolve_token(container.secrets_store, container.settings)
    return bool(token)
