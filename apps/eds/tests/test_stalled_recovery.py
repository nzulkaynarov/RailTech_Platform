"""Снятие зависших задач и политика очереди (ЗАВИС-1): общий lock `render_pdf` не должен вставать навсегда."""

import asyncio
import importlib
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from procrastinate import jobs, testing

from app.tasks import policy
from app.tasks.queue import TASK_MODULES, queue
from app.tasks.stalled import decide, recover_stalled_jobs


@pytest.fixture
def connector() -> Iterator[testing.InMemoryConnector]:
    connector = testing.InMemoryConnector()
    with queue.replace_connector(connector):
        yield connector


async def _no_ages(ids: object) -> dict[int, datetime]:
    return {}


def _load() -> set[str]:
    for module in TASK_MODULES:
        importlib.import_module(module)
    return set(queue.tasks)


def test_every_task_has_an_explicit_policy() -> None:
    assert _load() == set(policy.POLICIES)


def test_only_declared_idempotent_tasks_are_retried() -> None:
    assert decide("render_pdf") == "retried"
    assert decide("render_sweep") == "failed"
    assert decide("task_without_policy") == "failed"


async def test_a_render_of_a_dead_worker_is_retried_and_the_lock_is_released(
    connector: testing.InMemoryConnector,
) -> None:
    _load()
    stuck = await queue.tasks["render_pdf"].defer_async(render_hash="a")
    worker = await queue.job_manager.register_worker()
    assert (await queue.job_manager.fetch_job(queues=None, worker_id=worker)) is not None
    await queue.tasks["render_pdf"].defer_async(render_hash="b")
    assert await queue.job_manager.fetch_job(queues=None, worker_id=worker) is None  # общий lock держит первый

    connector.workers[worker] = datetime.now(UTC) - timedelta(minutes=10)
    recovered = await recover_stalled_jobs(queue.job_manager, started_at=_no_ages)

    assert [(r.job_id, r.action) for r in recovered] == [(stuck, "retried")]
    assert connector.jobs[stuck]["status"] == jobs.Status.TODO.value


async def test_a_periodic_job_of_a_dead_worker_is_failed(connector: testing.InMemoryConnector) -> None:
    _load()
    job_id = await queue.tasks["render_sweep"].defer_async(timestamp=1)
    worker = await queue.job_manager.register_worker()
    await queue.job_manager.fetch_job(queues=None, worker_id=worker)
    connector.workers[worker] = datetime.now(UTC) - timedelta(minutes=10)

    await recover_stalled_jobs(queue.job_manager, started_at=_no_ages)

    assert connector.jobs[job_id]["status"] == jobs.Status.FAILED.value


async def test_a_hanging_job_is_cancelled_by_its_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(policy.POLICIES, "hang", policy.JobPolicy(policy.Kind.PERIODIC, 0.05))

    async def hang() -> None:
        await asyncio.sleep(10)

    with pytest.raises(TimeoutError):
        await policy.enforce_timeout(hang, SimpleNamespace(job=SimpleNamespace(task_name="hang", id=1)), None)
