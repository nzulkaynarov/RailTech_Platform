"""Задачи Celery для rt_bus (ERP) — без жёсткой зависимости: Celery импортирует сервис, не пакет.

    from rt_bus.contrib.celery import install
    tasks = install(celery_app, get_bus)          # get_bus() -> DjangoBus
    bus.enqueue = tasks.enqueue                   # приёмник ставит обработку inbox в очередь
    bus.wakeup = tasks.wakeup                     # коммит транзакции с publish() будит pump без ожидания beat

Задачи: `rt_bus.pump` (раскладка + доставка; beat каждые `pump_seconds`), `rt_bus.process_inbox(event_id)`,
`rt_bus.requeue_stuck_inbox` и `rt_bus.log_metrics` (beat), `rt_bus.purge` (beat раз в сутки). Повторы доставки —
по `next_attempt_at` в таблице, не ретраями Celery: задачи без `autoretry`, сбой одной итерации подхватит следующая.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..django.bus import DjangoBus


@dataclass(frozen=True)
class CeleryTasks:
    pump: Any
    process_inbox: Any
    requeue_stuck_inbox: Any
    log_metrics: Any
    purge: Any

    def enqueue(self, event_id: str) -> None:
        self.process_inbox.delay(event_id)

    def wakeup(self) -> None:
        """Поставить `pump` вне расписания; очередь — та же, что у beat (`install(queue=)` или маршрутизация Celery)."""
        # один повтор подключения с паузой 0,2 с; само подключение ограничивает `broker_transport_options` сервиса
        # (`socket_connect_timeout`), иначе недоступный брокер держит коммитящий запрос до таймаута ОС
        policy = {"max_retries": 1, "interval_start": 0, "interval_max": 0.2}
        self.pump.apply_async(retry=True, retry_policy=policy)


def install(
    app: Any,
    get_bus: Callable[[], DjangoBus],
    *,
    pump_seconds: float = 5.0,
    sweep_seconds: float = 60.0,
    metrics_seconds: float = 300.0,
    purge_after: timedelta = timedelta(days=30),
    queue: str | None = None,
) -> CeleryTasks:
    options: dict[str, Any] = {"ignore_result": True}
    if queue:
        options["queue"] = queue

    @app.task(name="rt_bus.pump", **options)  # type: ignore[untyped-decorator]
    def pump() -> dict[str, int]:
        stats = get_bus().pump()
        return {"relayed": stats.relayed, "delivered": stats.deliver.delivered}

    @app.task(name="rt_bus.process_inbox", **options)  # type: ignore[untyped-decorator]
    def process_inbox(event_id: str) -> str | None:
        return get_bus().process_inbox(event_id)

    @app.task(name="rt_bus.requeue_stuck_inbox", **options)  # type: ignore[untyped-decorator]
    def requeue_stuck_inbox() -> int:
        return get_bus().requeue_stuck_inbox()

    @app.task(name="rt_bus.log_metrics", **options)  # type: ignore[untyped-decorator]
    def log_metrics() -> None:
        get_bus().log_metrics()

    @app.task(name="rt_bus.purge", **options)  # type: ignore[untyped-decorator]
    def purge() -> dict[str, int]:
        return get_bus().purge(purge_after)

    schedule = dict(app.conf.beat_schedule or {})
    schedule.update(
        {
            "rt_bus.pump": {"task": "rt_bus.pump", "schedule": pump_seconds, "options": {"expires": pump_seconds * 2}},
            "rt_bus.requeue_stuck_inbox": {"task": "rt_bus.requeue_stuck_inbox", "schedule": sweep_seconds},
            "rt_bus.log_metrics": {"task": "rt_bus.log_metrics", "schedule": metrics_seconds},
            "rt_bus.purge": {"task": "rt_bus.purge", "schedule": 86400.0},
        }
    )
    app.conf.beat_schedule = schedule
    return CeleryTasks(pump, process_inbox, requeue_stuck_inbox, log_metrics, purge)
