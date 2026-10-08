"""Проверки готовности против реальных зависимостей."""

import httpx
import pytest

from app import db
from app.config import Settings
from app.integrations import minio
from app.tasks.queue import queue


async def test_database_ping(live_settings: Settings) -> None:
    engine = db.create_engine(live_settings)
    try:
        await db.ping(engine)
    finally:
        await engine.dispose()


async def test_minio_ping(live_settings: Settings) -> None:
    async with httpx.AsyncClient(timeout=5) as client:
        await minio.ping(client, live_settings.minio_endpoint)


@pytest.mark.usefixtures("migrated_db")
async def test_procrastinate_sees_its_schema() -> None:
    async with queue.open_async():
        assert await queue.check_connection_async()
