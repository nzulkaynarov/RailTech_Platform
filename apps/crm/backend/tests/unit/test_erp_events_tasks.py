"""Задачи событий ERP (FIX-33): очередь по ключу события и периодический сборщик зависших."""

import pytest
from procrastinate import testing

from app.tasks import erp_events
from app.tasks.queue import queue


@pytest.mark.asyncio
async def test_enqueue_defers_under_a_per_event_queueing_lock() -> None:
    connector = testing.InMemoryConnector()
    with queue.replace_connector(connector):
        first = await erp_events.enqueue_erp_event("evt-1")
        again = await erp_events.enqueue_erp_event("evt-1")  # повтор от ERP или сборщик
        other = await erp_events.enqueue_erp_event("evt-2")

    assert first is not None
    assert again is None, "на одно событие ждёт одна задача"
    assert other is not None
    (job1, job2) = connector.jobs.values()
    assert job1["task_name"] == "process_erp_event"
    assert job1["queueing_lock"] == "erp_event:evt-1"
    assert job2["queueing_lock"] == "erp_event:evt-2"


def test_the_sweeper_runs_every_minute_and_never_piles_up() -> None:
    task = queue.tasks["erp_events_sweep"]
    assert task.queueing_lock == "erp_events_sweep"
    periodic = [p for p in queue.periodic_registry.periodic_tasks.values() if p.task is task]
    assert [p.cron for p in periodic] == ["* * * * *"]
