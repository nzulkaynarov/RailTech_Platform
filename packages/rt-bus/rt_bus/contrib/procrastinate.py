"""Задачи Procrastinate для rt_bus (CRM, EDS) — без жёсткой зависимости от procrastinate в ядре.

    from rt_bus.contrib.procrastinate import install
    tasks = install(procrastinate_app, get_bus)   # get_bus() -> AsyncBus
    bus.enqueue = tasks.enqueue

Периодические задачи (cron с шестым полем — секунды): `rt_bus.pump` (по умолчанию каждые 5 с),
`rt_bus.requeue_stuck_inbox` и `rt_bus.log_metrics` (каждую минуту / 5 минут), `rt_bus.purge` (раз в сутки);
`rt_bus.process_inbox(event_id)` — обработка записи inbox. `queueing_lock` не даёт копиться одинаковым периодическим
задачам. Повторы доставки — по `next_attempt_at`. Периодические задачи создают по задаче на тик: включите удаление
выполненных (`worker(delete_jobs="successful")`).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..sqlalchemy.bus import AsyncBus


@dataclass(frozen=True)
class ProcrastinateTasks:
    pump: Any
    process_inbox: Any
    requeue_stuck_inbox: Any
    log_metrics: Any
    purge: Any

    async def enqueue(self, event_id: str) -> None:
        await self.process_inbox.defer_async(event_id=event_id)


def install(
    app: Any,
    get_bus: Callable[[], AsyncBus],
    *,
    pump_cron: str = "* * * * * */5",
    sweep_cron: str = "* * * * *",
    metrics_cron: str = "*/5 * * * *",
    purge_cron: str = "17 3 * * *",
    purge_after: timedelta = timedelta(days=30),
    queue: str = "rt_bus",
) -> ProcrastinateTasks:
    @app.periodic(cron=pump_cron)  # type: ignore[untyped-decorator]
    @app.task(name="rt_bus.pump", queue=queue, queueing_lock="rt_bus.pump")  # type: ignore[untyped-decorator]
    async def pump(timestamp: int) -> None:
        await get_bus().pump()

    @app.task(name="rt_bus.process_inbox", queue=queue)  # type: ignore[untyped-decorator]
    async def process_inbox(event_id: str) -> None:
        await get_bus().process_inbox(event_id)

    @app.periodic(cron=sweep_cron)  # type: ignore[untyped-decorator]
    @app.task(name="rt_bus.requeue_stuck_inbox", queue=queue, queueing_lock="rt_bus.requeue_stuck_inbox")  # type: ignore[untyped-decorator]
    async def requeue_stuck_inbox(timestamp: int) -> None:
        await get_bus().requeue_stuck_inbox()

    @app.periodic(cron=metrics_cron)  # type: ignore[untyped-decorator]
    @app.task(name="rt_bus.log_metrics", queue=queue, queueing_lock="rt_bus.log_metrics")  # type: ignore[untyped-decorator]
    async def log_metrics(timestamp: int) -> None:
        await get_bus().log_metrics()

    @app.periodic(cron=purge_cron)  # type: ignore[untyped-decorator]
    @app.task(name="rt_bus.purge", queue=queue, queueing_lock="rt_bus.purge")  # type: ignore[untyped-decorator]
    async def purge(timestamp: int) -> None:
        await get_bus().purge(purge_after)

    return ProcrastinateTasks(pump, process_inbox, requeue_stuck_inbox, log_metrics, purge)
