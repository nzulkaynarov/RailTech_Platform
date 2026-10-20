"""Задача передачи клиента в ERP после коммита клиента (FIX-31, ADR-0022).

Одна блокировка на клиента (`lock`): передачи одного клиента идут по очереди; `queueing_lock` не
даёт поставить вторую задачу, пока первая ждёт, — двойной клик менеджера не плодит задач.
Постоянные ошибки (409 `INN_CONFLICT`, 422, нет согласия) записывает `ErpHandoffService` и не
повторяет; временные задача пробрасывает, и Procrastinate повторяет по расписанию `RETRY`.
На последней попытке итог — `failed`.
"""

from procrastinate import JobContext, RetryStrategy
from procrastinate.exceptions import AlreadyEnqueued

from app.container import get_container
from app.tasks.queue import queue

RETRY = RetryStrategy(max_attempts=6, linear_wait=30)


def handoff_lock(client_id: int) -> str:
    return f"erp_handoff:{client_id}"


@queue.task(name="erp_handoff_client", queue="notify", retry=RETRY, pass_context=True)
async def erp_handoff_client(
    context: JobContext, client_id: int, lead_id: int, actor_user_id: int | None = None
) -> str:
    # `job.attempts` — число прошлых попыток (0 при первом запуске); Procrastinate повторяет, пока
    # `attempts < max_attempts`, так что последний запуск — при `attempts == max_attempts`.
    final = context.job.attempts >= (RETRY.max_attempts or 0)
    outcome: str = await get_container().erp_handoff_service.run(
        client_id, lead_id, actor_user_id, final_attempt=final
    )
    return outcome


async def enqueue_erp_handoff(client_id: int, lead_id: int, actor_user_id: int) -> int | None:
    """Поставить передачу; `None` — такая же задача уже ждёт в очереди (повторный клик)."""
    try:
        job_id: int = await erp_handoff_client.configure(
            lock=handoff_lock(client_id), queueing_lock=handoff_lock(client_id)
        ).defer_async(client_id=client_id, lead_id=lead_id, actor_user_id=actor_user_id)
    except AlreadyEnqueued:
        return None
    return job_id


__all__ = ["RETRY", "enqueue_erp_handoff", "erp_handoff_client", "handoff_lock"]
