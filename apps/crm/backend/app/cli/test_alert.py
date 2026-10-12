"""`python -m app test-alert` — тестовый пост в канал команды (чек-лист переезда, PLAN Фаза 9).

Проверяет цепочку «бот → канал»: токен, `notifications.channel_id`, права бота в канале.
"""

import argparse

from app.container import get_container


async def run(_: argparse.Namespace) -> int:
    c = get_container()
    cfg = await c.settings_service.get()
    channel, bot = cfg.notifications.channel_id, await c.telegram_bot()
    if bot is None or channel is None:
        print("Не настроено: TELEGRAM_BOT_TOKEN и/или Настройки → notifications.channel_id")  # noqa: T201
        return 1
    try:
        await bot.send_message(channel, "⚠️ Тестовый алерт RailTech CRM: канал настроен верно.")
    finally:
        await c.aclose()
    print(f"Отправлено в канал {channel}")  # noqa: T201
    return 0
