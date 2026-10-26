"""Задачи шины rt_bus в очереди CRM (B4): регистрация, расписание, постановка обработки inbox."""

import asyncio

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


@pytest.mark.asyncio
async def test_the_wakeup_defers_one_pump_to_the_bus_queue() -> None:
    """Пробуждение по коммиту (B5a) — `rt_bus.pump` в очереди `rt_bus` со своим ключом
    (с периодическим проходом не сливается, W11B-G-6); второе пробуждение не копится."""
    connector = testing.InMemoryConnector()
    with queue.replace_connector(connector):
        await bus_tasks.tasks.wakeup()
        await bus_tasks.tasks.wakeup()

    (job,) = connector.jobs.values()
    assert (job["task_name"], job["queue_name"], job["queueing_lock"]) == (
        "rt_bus.pump",
        "rt_bus",
        "rt_bus.pump.wakeup",
    )


def test_the_container_bus_wakes_the_pump_after_commit() -> None:
    from app.config import Settings
    from app.container import Container

    bus = Container(Settings(_env_file=None, app_env="test")).bus
    assert bus.wakeup == bus_tasks.tasks.wakeup
    assert bus.enqueue == bus_tasks.tasks.enqueue


@pytest.mark.asyncio
async def test_drain_bus_waits_for_pending_wakeups_only_when_the_bus_exists() -> None:
    from app.config import Settings
    from app.container import Container

    container = Container(Settings(_env_file=None, app_env="test"))
    await container.drain_bus()  # шины нет — ничего не создаётся
    assert "bus" not in container.__dict__

    connector = testing.InMemoryConnector()
    with queue.replace_connector(connector):
        task = asyncio.create_task(bus_tasks.tasks.wakeup())
        container.bus._wake_tasks.add(task)
        await container.drain_bus()
    assert task.done()
    assert [job["task_name"] for job in connector.jobs.values()] == ["rt_bus.pump"]


def test_the_old_erp_event_tasks_are_gone() -> None:
    assert "process_erp_event" not in queue.tasks
    assert "erp_events_sweep" not in queue.tasks


@pytest.mark.asyncio
async def test_the_worker_polls_the_queue_every_second(monkeypatch: pytest.MonkeyPatch) -> None:
    """W11B-G-6: воркер CRM опрашивает очередь раз в секунду (`WORKER_OPTIONS`)."""
    from typing import Any

    from app.__main__ import _run_worker

    seen: dict[str, Any] = {}

    async def fake_run_worker(**kwargs: Any) -> None:
        seen.update(kwargs)

    monkeypatch.setattr(queue, "run_worker_async", fake_run_worker)
    with queue.replace_connector(testing.InMemoryConnector()):
        await _run_worker()
    assert seen["fetch_job_polling_interval"] <= 1.0
