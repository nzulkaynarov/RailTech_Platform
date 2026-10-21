"""Задачи синхронизации сотрудников с ERP (FIX-11, M3-CRM-06): провижининг и отзыв сессий.

Одна блокировка на пользователя (`lock`): его задачи идут по очереди, провижининг не обгоняет отзыв.
Повторы — Procrastinate; итог и ошибки пишет `ErpAccessService` (ленту внешних сервисов, ADR-0024).
"""

from app.container import get_container
from app.tasks.erp_retry import ErpRetryStrategy
from app.tasks.queue import queue

RETRY = ErpRetryStrategy(max_attempts=6, linear_wait=30)


def user_lock(user_id: int) -> str:
    return f"erp_user:{user_id}"


@queue.task(name="erp_provision_user", queue="notify", retry=RETRY)
async def erp_provision_user(user_id: int) -> str:
    outcome: str = await get_container().erp_access_service.provision(user_id)
    return outcome


@queue.task(name="erp_revoke_sessions", queue="notify", retry=RETRY)
async def erp_revoke_sessions(user_id: int) -> str:
    outcome: str = await get_container().erp_access_service.revoke(user_id)
    return outcome


async def enqueue_erp_sync(action: str, user_id: int) -> int:
    """Поставить задачу по решению `domain.erp_sync.sync_action`; возвращает id задания."""
    task = erp_provision_user if action == "provision" else erp_revoke_sessions
    job_id: int = await task.configure(lock=user_lock(user_id)).defer_async(user_id=user_id)
    return job_id
