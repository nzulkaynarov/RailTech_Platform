"""Задачи шины rt_bus в очереди CRM (B4): регистрация, расписание, постановка обработки inbox."""

import pytest
from procrastinate import testing

from app.tasks import bus as bus_tasks
from app.tasks.queue import queue


def _periodic(task_name: str) -> list[str]:
    task = queue.tasks[task_name]
    return [p.cron for p in queue.periodic_registry.periodic_tasks.values() if p.task is task]


def test_the_pump_runs_every_five_seconds_and_never_piles_up() -> None:
    task = queue.tasks["rt_bus.pump"]
    assert task.queueing_lock == "rt_bus.pump"
    assert _periodic("rt_bus.pump") == ["* * * * * */5"]


@pytest.mark.parametrize(
    ("name", "cron"),
    [
        ("rt_bus.requeue_stuck_inbox", "* * * * *"),
        ("rt_bus.log_metrics", "*/5 * * * *"),
        ("rt_bus.purge", "17 3 * * *"),
        ("erp_notices_sweep", "* * * * *"),
        ("rt_bus_jobs_cleanup", "7 * * * *"),
    ],
)
def test_periodic_tasks_are_registered_with_their_schedule(name: str, cron: str) -> None:
    assert _periodic(name) == [cron]
    assert queue.tasks[name].queueing_lock == name


@pytest.mark.asyncio
async def test_a_received_event_is_deferred_to_the_process_inbox_task() -> None:
    connector = testing.InMemoryConnector()
    with queue.replace_connector(connector):
        await bus_tasks.tasks.enqueue("00000000-0000-4000-8000-000000000001")

    (job,) = connector.jobs.values()
    assert job["task_name"] == "rt_bus.process_inbox"
    assert job["args"] == {"event_id": "00000000-0000-4000-8000-000000000001"}


def test_the_old_erp_event_tasks_are_gone() -> None:
    assert "process_erp_event" not in queue.tasks
    assert "erp_events_sweep" not in queue.tasks
