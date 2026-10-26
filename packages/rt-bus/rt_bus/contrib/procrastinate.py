"""Задачи Procrastinate для rt_bus (CRM, EDS) — без жёсткой зависимости от procrastinate в ядре.

    from rt_bus.contrib.procrastinate import install
    tasks = install(procrastinate_app, get_bus)   # get_bus() -> AsyncBus
    bus.enqueue, bus.wakeup = tasks.enqueue, tasks.wakeup

Периодические задачи (cron с шестым полем — секунды): `rt_bus.pump` (по умолчанию каждые 5 с),
`rt_bus.requeue_stuck_inbox` и `rt_bus.log_metrics` (каждую минуту / 5 минут), `rt_bus.purge` (раз в сутки);
`rt_bus.process_inbox(event_id)` — обработка записи inbox. `queueing_lock` не даёт копиться одинаковым
периодическим задачам. Пробуждение по коммиту (`wakeup()`, `AsyncBus.wakeup`) — отдельная задача `rt_bus.pump` со
своим ключом `rt_bus.pump.wakeup`: с периодическим проходом она не сливается (тот мог быть поставлен раньше и ещё не
стартовать, W11B-G-6), сливаются только пробуждения между собой — ожидающая ещё не начала раскладку и заберёт новое
событие. Два `pump` одновременно безопасны (`FOR UPDATE SKIP LOCKED`, итоги — по подписчикам в порядке имён). Повторы
доставки — по `next_attempt_at`. Периодические задачи создают по задаче на тик: включите удаление выполненных
(`worker(delete_jobs="successful")`).

Воркер: `**WORKER_OPTIONS` в `run_worker_async` — опрос очереди раз в секунду вместо 5 с. Флаг NOTIFY сбрасывается после
каждой выборки, и уведомление, пришедшее во время выборки, не будит воркер: задача ждёт ближайшего опроса, при 5 с это
и есть «хвост» пробуждения.
"""

from __future__ import annotations

import contextlib
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..sqlalchemy.bus import AsyncBus


#: Ключ очереди пробуждения: отдельный от периодического `pump`, иначе пробуждение сливается с ним (см. модуль).
WAKEUP_LOCK = "rt_bus.pump.wakeup"
PUMP_LOCK = "rt_bus.pump"

#: Параметры `run_worker_async` для воркера с шиной: верхняя граница ожидания задачи, если NOTIFY потерялся (≤ 1 с).
WORKER_OPTIONS: dict[str, Any] = {"fetch_job_polling_interval": 1.0}


@dataclass(frozen=True)
class ProcrastinateTasks:
    pump: Any
    process_inbox: Any
    requeue_stuck_inbox: Any
    log_metrics: Any
    purge: Any

    async def enqueue(self, event_id: str) -> None:
        await self.process_inbox.defer_async(event_id=event_id)

    async def wakeup(self) -> None:
        """Поставить `pump` вне расписания со своим ключом `rt_bus.pump.wakeup`. Уже есть ожидающее пробуждение — оно и
        заберёт событие (`AlreadyEnqueued`, норма); с периодическим проходом пробуждение не сливается."""
        from procrastinate.exceptions import AlreadyEnqueued

        with contextlib.suppress(AlreadyEnqueued):
            await self.pump.configure(queueing_lock=WAKEUP_LOCK).defer_async(timestamp=int(time.time()))


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
    @app.task(name="rt_bus.pump", queue=queue, queueing_lock=PUMP_LOCK)  # type: ignore[untyped-decorator]
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
