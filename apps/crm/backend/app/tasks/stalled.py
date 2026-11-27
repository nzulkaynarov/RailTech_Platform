"""Зависшие задачи очереди (ЗАВИС-1): найти по сердцебиению воркера и снять по политике задачи.

Воркер остановили в разгар задачи (деплой, нехватка памяти) — она осталась в `doing`; при `lock`
следующие такие же не стартуют (так встал опрос общего ящика на дни). Здесь — страховка:

- при старте воркера и раз в 3 минуты берём задачи в `doing` у воркеров без сердцебиения
  (`job_manager.get_stalled_jobs`), политика из `app.tasks.policy` решает: упала / в очередь заново;
- без политики задача не повторяется никогда — только `failed` и запись в журнал.
"""

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

import structlog
from procrastinate import jobs
from procrastinate.manager import JobManager

from app.tasks.policy import Kind, policy_of
from app.tasks.queue import queue

logger = structlog.get_logger(__name__)

# Воркер шлёт сердцебиение раз в 10 с; без него дольше этого — считаем остановленным.
HEARTBEAT_TIMEOUT_S: Final = 90.0
StartedAt = Callable[[Sequence[int]], Awaitable[Mapping[int, datetime]]]


@dataclass(frozen=True, slots=True)
class Recovered:
    job_id: int
    task: str
    action: str  # "failed" | "retried"
    age_s: float | None


def decide(task_name: str) -> str:
    """«retried» — только если задача явно объявлена идемпотентной; всё остальное — «failed»."""
    policy = policy_of(task_name)
    return "retried" if policy is not None and policy.kind is Kind.IDEMPOTENT else "failed"


async def _started_at(manager: JobManager, ids: Sequence[int]) -> Mapping[int, datetime]:
    """Когда задачи стартовали — для журнала; нет данных (другой коннектор) — пусто."""
    try:
        rows = await manager.connector.execute_query_all_async(
            query=(
                "SELECT job_id, max(at) AS at FROM procrastinate_events "
                "WHERE type = 'started' AND job_id = ANY(%(ids)s) GROUP BY job_id"
            ),
            ids=list(ids),
        )
    except Exception:  # noqa: BLE001 — возраст нужен только журналу
        return {}
    return {int(r["job_id"]): r["at"] for r in rows}


async def recover_stalled_jobs(
    manager: JobManager,
    *,
    now: datetime | None = None,
    started_at: StartedAt | None = None,
    heartbeat_timeout_s: float = HEARTBEAT_TIMEOUT_S,
) -> list[Recovered]:
    """Снять зависшие задачи; безопасно вызывать часто и из нескольких воркеров."""
    now = now or datetime.now(UTC)
    await manager.prune_stalled_workers(heartbeat_timeout_s)
    stalled = [
        j
        for j in await manager.get_stalled_jobs(seconds_since_heartbeat=heartbeat_timeout_s)
        if j.id is not None
    ]
    if not stalled:
        return []
    ids = [int(j.id) for j in stalled if j.id is not None]
    started = await (started_at(ids) if started_at else _started_at(manager, ids))
    out: list[Recovered] = []
    for job in stalled:
        job_id = int(job.id or 0)
        action = decide(job.task_name)
        if action == "retried":
            await manager.retry_job_by_id_async(job_id, retry_at=now)
        else:
            await manager.finish_job_by_id_async(job_id, jobs.Status.FAILED, delete_job=False)
        began = started.get(job_id)
        age = (now - began).total_seconds() if began else None
        out.append(Recovered(job_id, job.task_name, action, age))
        logger.warning(
            "stalled_job_recovered", task=job.task_name, job_id=job_id, action=action, age_s=age
        )
    return out


async def recover_on_worker_start() -> list[Recovered]:
    """Вызов из процесса воркера после открытия очереди: сбой не мешает старту."""
    try:
        return await recover_stalled_jobs(queue.job_manager)
    except Exception as exc:  # noqa: BLE001
        logger.error("stalled_recovery_failed", error=type(exc).__name__)
        return []


@queue.periodic(cron="*/3 * * * *", periodic_id="stalled_jobs_recovery")
@queue.task(name="stalled_jobs_recovery", queue="timers", queueing_lock="stalled_jobs_recovery")
async def stalled_jobs_recovery(timestamp: int) -> int:
    return len(await recover_stalled_jobs(queue.job_manager))


__all__ = [
    "Recovered",
    "decide",
    "recover_on_worker_start",
    "recover_stalled_jobs",
    "stalled_jobs_recovery",
]
