"""`python -m app telegram-webhook info|set|delete` — webhook prod-бота (PLAN Фаза 8).

API ставит webhook сам при старте (`TELEGRAM_MODE=webhook`); команда — для диагностики
(`info`: очередь и последняя ошибка Telegram) и ручной переустановки после смены домена
или `TELEGRAM_WEBHOOK_SECRET`.
"""

import argparse

from aiogram import Bot

from app.config import get_settings

ALLOWED_UPDATES = ["message", "callback_query"]  # = dispatcher.resolve_used_update_types()


async def run(args: argparse.Namespace) -> int:
    settings = get_settings()
    token = settings.telegram_bot_token.get_secret_value()
    if not token:
        print("TELEGRAM_BOT_TOKEN не задан")  # noqa: T201 — CLI-вывод
        return 1
    bot = Bot(token)
    try:
        if args.action == "set":
            if (
                not settings.telegram_webhook_url
                or not settings.telegram_webhook_secret.get_secret_value()
            ):
                print("Нужны TELEGRAM_WEBHOOK_URL и TELEGRAM_WEBHOOK_SECRET")  # noqa: T201
                return 1
            await bot.set_webhook(
                str(settings.telegram_webhook_url),
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
