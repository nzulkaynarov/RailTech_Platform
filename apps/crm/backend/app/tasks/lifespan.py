"""Открытие приложения Procrastinate в процессе API (для постановки задач)."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from app.config import Settings


@asynccontextmanager
async def queue_lifespan(settings: Settings) -> AsyncIterator[None]:
    """Без бота задачи из API не ставятся — пул соединений не открываем."""
    if settings.telegram_mode == "disabled" or not settings.telegram_bot_token.get_secret_value():
        yield
        return
    from app.tasks.queue import queue

    async with queue.open_async():
        yield
