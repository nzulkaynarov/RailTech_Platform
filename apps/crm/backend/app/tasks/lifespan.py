"""Открытие приложения Procrastinate в процессе API (для постановки задач)."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from app.config import Settings


@asynccontextmanager
async def queue_lifespan(settings: Settings) -> AsyncIterator[None]:
    """В тестах (`APP_ENV=test`) пул очереди не открывается: постановка задач логируется."""
    if settings.app_env == "test":
        yield
        return
    from app.tasks.queue import queue

    async with queue.open_async():
        yield
