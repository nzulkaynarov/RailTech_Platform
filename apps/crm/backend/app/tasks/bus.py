"""Фоновые задачи шины rt_bus в CRM (B4, CONTRACTS §9, runbook `rt-bus-crm`).

Библиотека регистрирует периодические `rt_bus.pump` (раскладка outbox и доставка, каждые 5 с),
`rt_bus.requeue_stuck_inbox` (зависшие записи inbox, раз в минуту), `rt_bus.log_metrics` и
`rt_bus.purge`, а также задачу `rt_bus.process_inbox` — обработка принятого события. Здесь к ним
добавлены:
* `erp_notices_sweep` — недосланные сообщения Telegram по событиям ERP (сервис упал между
  коммитом обработки и отправкой);
* `rt_bus_jobs_cleanup` — pump и сборщик создают по задаче на тик, успешные удаляются раз в час.
"""

from rt_bus.contrib.procrastinate import install

from app.container import get_container
from app.tasks.queue import queue

tasks = install(queue, lambda: get_container().bus)

JOBS_KEEP_HOURS = 1


@queue.periodic(cron="* * * * *", periodic_id="erp_notices_sweep")
@queue.task(name="erp_notices_sweep", queue="notify", queueing_lock="erp_notices_sweep")
async def erp_notices_sweep(timestamp: int) -> int:
    """Раз в минуту: сообщения событий ERP, которые не ушли после коммита обработки."""
    return await get_container().erp_notices.sweep()


@queue.periodic(cron="7 * * * *", periodic_id="rt_bus_jobs_cleanup")
@queue.task(name="rt_bus_jobs_cleanup", queue="rt_bus", queueing_lock="rt_bus_jobs_cleanup")
async def rt_bus_jobs_cleanup(timestamp: int) -> None:
    await queue.job_manager.delete_old_jobs(nb_hours=JOBS_KEEP_HOURS, queue="rt_bus")
