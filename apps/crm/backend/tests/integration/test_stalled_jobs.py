"""Задача мёртвого воркера снимается, и опрос ящика снова идёт (ЗАВИС-1): реальная очередь."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.services.system_status import STALLED
from app.tasks.inbound_mail import inbound_mail_poll
from app.tasks.queue import queue
from app.tasks.stalled import recover_stalled_jobs

pytestmark = pytest.mark.integration

LOCK = "inbound_mail_poll"


async def _seed_stuck_poll(sessions: async_sessionmaker[AsyncSession]) -> int:
    """Опрос в `doing` у воркера, молчащего пять дней."""
    async with sessions() as session, session.begin():
        await session.execute(text("DELETE FROM procrastinate_workers"))
        worker = await session.execute(
            text(
                "INSERT INTO procrastinate_workers (last_heartbeat) "
                "VALUES (now() - interval '5 days') RETURNING id"
            )
        )
        job = await session.execute(
            text(
                "INSERT INTO procrastinate_jobs "
                "(queue_name, task_name, lock, queueing_lock, status, args, worker_id) "
                "VALUES ('timers', 'inbound_mail_poll', :lock, :lock, 'doing', '{}', :worker) "
                "RETURNING id"
            ),
            {"lock": LOCK, "worker": worker.scalar_one()},
        )
        job_id = int(job.scalar_one())
        await session.execute(
            text(
                "INSERT INTO procrastinate_events (job_id, type, at) "
                "VALUES (:id, 'started', now() - interval '5 days')"
            ),
            {"id": job_id},
        )
        return job_id


async def _stalled(sessions: async_sessionmaker[AsyncSession]) -> int:
    now = datetime.now(UTC)
    async with sessions() as session:
        result = await session.execute(
            STALLED,
            {"before": now - timedelta(minutes=15), "heartbeat_after": now - timedelta(seconds=90)},
        )
        return int(result.scalar_one())


async def test_stuck_poll_is_failed_and_the_next_one_can_start(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    job_id = await _seed_stuck_poll(sessions)
    assert await _stalled(sessions) == 1

    async with queue.open_async():
        # следующий опрос ждёт: пока первый «выполняется», lock его не пускает
        await inbound_mail_poll.configure(queueing_lock=None).defer_async(timestamp=1)
        worker_id = await queue.job_manager.register_worker()
        assert await queue.job_manager.fetch_job(queues=None, worker_id=worker_id) is None

        recovered = await recover_stalled_jobs(queue.job_manager)

        assert [(r.job_id, r.action) for r in recovered] == [(job_id, "failed")]
        assert recovered[0].age_s is not None
        assert recovered[0].age_s > 4 * 86400
        started = await queue.job_manager.fetch_job(queues=None, worker_id=worker_id)
        assert started is not None
        assert started.task_name == "inbound_mail_poll"
        await queue.job_manager.unregister_worker(worker_id)

    async with sessions() as session:
        status = (
            await session.execute(
                text("SELECT status FROM procrastinate_jobs WHERE id = :id"), {"id": job_id}
            )
        ).scalar_one()
    assert status == "failed"


async def test_the_status_counter_returns_to_zero_after_recovery(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    await _seed_stuck_poll(sessions)
    assert await _stalled(sessions) == 1

    async with queue.open_async():
        await recover_stalled_jobs(queue.job_manager)

    assert await _stalled(sessions) == 0
