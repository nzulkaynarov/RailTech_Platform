"""Постановка задач синхронизации с ERP в очередь после коммита (пользователи и роли)."""

from collections.abc import Awaitable, Callable

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.repositories import users as repo

logger = structlog.get_logger(__name__)
# Поставить в очередь синхронизацию с ERP (`tasks.erp_users.enqueue_erp_sync`): (действие, user_id).
ErpSyncEnqueue = Callable[[str, int], Awaitable[object]]


async def enqueue_sync(
    sessions: async_sessionmaker[AsyncSession],
    enqueue: ErpSyncEnqueue | None,
    action: str | None,
    user_id: int,
) -> None:
    """Задача в очередь; сбой очереди не роняет запрос — он оседает в `erp_sync_error` и в ленте."""
    if action is None or enqueue is None:
        return
    try:
        await enqueue(action, user_id)
    except Exception:
        logger.exception("erp_sync_enqueue_failed", user_id=user_id, action=action)
        async with sessions() as session, session.begin():
            await repo.set_erp_sync_error(
                session, user_id, f"{action}: задача не поставлена в очередь"
            )
