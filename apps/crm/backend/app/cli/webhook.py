"""`python -m app telegram-webhook info|set|delete` — webhook prod-бота (PLAN Фаза 8).

API ставит webhook сам при старте (`TELEGRAM_MODE=webhook`); команда — для диагностики
(`info`: очередь и последняя ошибка Telegram) и ручной переустановки после смены домена
или `TELEGRAM_WEBHOOK_SECRET`.
"""

import argparse

from aiogram import Bot

from app.config import get_settings
from app.container import get_container
from app.domain.telegram_webhook import PROBLEM_TEXT, webhook_url_problem
from app.integrations.telegram import resolve_token

# = dispatcher.resolve_used_update_types()
ALLOWED_UPDATES = ["message", "callback_query", "my_chat_member"]


async def run(args: argparse.Namespace) -> int:
    settings = get_settings()
    container = get_container()
    try:
        token, _ = await resolve_token(container.secrets_store, settings)
    finally:
        await container.aclose()
    if not token:
        print("Токен бота не задан: «Подключения» в CRM или TELEGRAM_BOT_TOKEN")  # noqa: T201
        return 1
    bot = Bot(token)
    try:
        if args.action == "set":
            problem = webhook_url_problem(settings.telegram_webhook_url)
            if problem is not None:
                print(f"{PROBLEM_TEXT[problem]} (https://<CRM_DOMAIN>/telegram/webhook)")  # noqa: T201
                return 1
            if not settings.telegram_webhook_secret.get_secret_value():
                print("Нужен TELEGRAM_WEBHOOK_SECRET")  # noqa: T201
                return 1
            await bot.set_webhook(
                settings.telegram_webhook_url.strip(),
                secret_token=settings.telegram_webhook_secret.get_secret_value(),
                allowed_updates=ALLOWED_UPDATES,
            )
        elif args.action == "delete":
            await bot.delete_webhook(drop_pending_updates=False)
        info = await bot.get_webhook_info()
    finally:
        await bot.session.close()
    print(f"url: {info.url or '—'}")  # noqa: T201
    print(f"pending_update_count: {info.pending_update_count}")  # noqa: T201
    print(f"allowed_updates: {info.allowed_updates}")  # noqa: T201
    if info.last_error_message:
        print(f"last_error: {info.last_error_date} {info.last_error_message}")  # noqa: T201
    return 0
