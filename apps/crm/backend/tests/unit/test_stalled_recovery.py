"""Снятие зависших задач (ЗАВИС-1): умерший воркер не должен блокировать очередь."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from procrastinate import jobs, testing

from app.tasks.inbound_mail import inbound_mail_poll
from app.tasks.queue import queue
from app.tasks.stalled import recover_stalled_jobs


@pytest.fixture
def connector() -> Iterator[testing.InMemoryConnector]:
    connector = testing.InMemoryConnector()
    with queue.replace_connector(connector):
        yield connector


async def _start(
    connector: testing.InMemoryConnector, task: str, **kwargs: object
) -> tuple[int, int]:
    """Поставить задачу и взять её воркером (`doing`); вернуть (id задачи, id воркера)."""
    job_id = await queue.tasks[task].defer_async(**kwargs)
    worker_id = await queue.job_manager.register_worker()
    job = await queue.job_manager.fetch_job(queues=None, worker_id=worker_id)
    assert job is not None
    assert job.id == job_id
    return job_id, worker_id


def _kill_worker(connector: testing.InMemoryConnector, worker_id: int) -> None:
    connector.workers[worker_id] = datetime.now(UTC) - timedelta(minutes=10)


@pytest.mark.asyncio
async def test_a_job_of_a_dead_worker_is_failed_and_the_next_poll_can_run(
    connector: testing.InMemoryConnector,
) -> None:
    job_id, worker_id = await _start(connector, "inbound_mail_poll", timestamp=1)
    # пока застрявшая «выполняется», новая с тем же lock не стартует
    await queue.tasks["inbound_mail_poll"].defer_async(timestamp=2)
    assert await queue.job_manager.fetch_job(queues=None, worker_id=worker_id) is None

    _kill_worker(connector, worker_id)
    recovered = await recover_stalled_jobs(queue.job_manager, started_at=_no_ages)

    assert [(r.job_id, r.action) for r in recovered] == [(job_id, "failed")]
    assert connector.jobs[job_id]["status"] == jobs.Status.FAILED.value
    new_worker = await queue.job_manager.register_worker()
    nxt = await queue.job_manager.fetch_job(queues=None, worker_id=new_worker)
    assert nxt is not None
    assert nxt.task_name == "inbound_mail_poll"


async def _no_ages(ids: object) -> dict[int, datetime]:
    return {}


@pytest.mark.asyncio
async def test_an_idempotent_job_is_retried_but_a_non_idempotent_one_is_not(
    connector: testing.InMemoryConnector,
) -> None:
    idem_id, w1 = await _start(connector, "erp_create_request", deal_id=1)
    once_id, w2 = await _start(connector, "send_email", email_log_id=1)
    _kill_worker(connector, w1)
    _kill_worker(connector, w2)

    recovered = {
        r.job_id: r.action
        for r in await recover_stalled_jobs(queue.job_manager, started_at=_no_ages)
    }

    assert recovered == {idem_id: "retried", once_id: "failed"}
    assert connector.jobs[idem_id]["status"] == jobs.Status.TODO.value
    assert connector.jobs[once_id]["status"] == jobs.Status.FAILED.value


@pytest.mark.asyncio
async def test_a_job_of_a_live_worker_is_left_alone(connector: testing.InMemoryConnector) -> None:
    job_id, _ = await _start(connector, "inbound_mail_poll", timestamp=1)

    assert await recover_stalled_jobs(queue.job_manager, started_at=_no_ages) == []
    assert connector.jobs[job_id]["status"] == jobs.Status.DOING.value


@pytest.mark.asyncio
async def test_recovery_reports_the_age_of_the_job(connector: testing.InMemoryConnector) -> None:
    job_id, worker_id = await _start(connector, "inbound_mail_poll", timestamp=1)
    _kill_worker(connector, worker_id)
    now = datetime.now(UTC)

    async def ages(ids: object) -> dict[int, datetime]:
        return {job_id: now - timedelta(days=5)}

    (done,) = await recover_stalled_jobs(queue.job_manager, now=now, started_at=ages)
    assert done.age_s == pytest.approx(5 * 86400)


def test_the_poll_task_is_registered_with_its_lock() -> None:
    assert inbound_mail_poll.lock == "inbound_mail_poll"
