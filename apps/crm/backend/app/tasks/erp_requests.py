"""Задача «Создать заявку» → ERP после коммита (CRM-03, W16-D1-2): `services/erp_requests.py`.

Блокировка — общая с передачей клиента (`handoff_lock`): заявка клиента, которого ещё передают, ждёт
передачу, а не передаёт его второй раз. `queueing_lock` по заявке — повторный клик не ставит вторую
задачу. Постоянные ошибки записываются и не повторяются; временные — повтор по `RETRY`, на последней
попытке — `failed`.
"""

from procrastinate import JobContext
from procrastinate.exceptions import AlreadyEnqueued

from app.container import get_container
from app.tasks.erp_handoff import RETRY, handoff_lock
from app.tasks.queue import queue


def request_lock(deal_id: int) -> str:
    return f"erp_request:{deal_id}"


@queue.task(name="erp_create_request", queue="notify", retry=RETRY, pass_context=True)
async def erp_create_request(
    context: JobContext, deal_id: int, actor_user_id: int | None = None
) -> str:
    final = context.job.attempts >= (RETRY.max_attempts or 0)
    outcome: str = await get_container().erp_request_service.run(
        deal_id, actor_user_id, final_attempt=final
    )
    return outcome


async def enqueue_erp_request(deal_id: int, client_id: int, actor_user_id: int) -> int | None:
    """Поставить заявку в ERP; `None` — такая же задача уже ждёт в очереди."""
    try:
        job_id: int = await erp_create_request.configure(
            lock=handoff_lock(client_id), queueing_lock=request_lock(deal_id)
        ).defer_async(deal_id=deal_id, actor_user_id=actor_user_id)
    except AlreadyEnqueued:
        return None
    return job_id


__all__ = ["enqueue_erp_request", "erp_create_request", "request_lock"]
