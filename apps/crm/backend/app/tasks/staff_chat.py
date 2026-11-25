"""Staff leaves the team channel and client groups (ОНБ-1.2): removal task, daily reconciliation."""

import structlog
from procrastinate import RetryStrategy

from app.container import get_container
from app.tasks.queue import queue

logger = structlog.get_logger(__name__)
RETRY = RetryStrategy(max_attempts=5, exponential_wait=30)


@queue.task(name="staff_chat_removal", queue="notify", retry=RETRY)
async def staff_chat_removal(user_id: int, tg_user_id: int) -> int:
    result = await get_container().staff_channel.remove_member(user_id, tg_user_id)
    return result.removed


@queue.periodic(cron="30 21 * * *", periodic_id="staff_chat_reconcile")  # 02:30 Tashkent
@queue.task(name="staff_chat_reconcile", queue="notify", queueing_lock="staff_chat_reconcile")
async def staff_chat_reconcile(timestamp: int) -> int:
    return await get_container().staff_channel.reconcile()


async def enqueue_staff_chat_removal(user_id: int, tg_user_id: int) -> None:
    """Queue the removal; a queue failure is only logged: the daily job covers deactivated staff."""
    try:
        await staff_chat_removal.defer_async(user_id=user_id, tg_user_id=tg_user_id)
    except Exception:
        logger.exception("staff_chat_removal_enqueue_failed", user_id=user_id)
