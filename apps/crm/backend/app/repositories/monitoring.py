"""Метрики эксплуатации для монитора и дневного отчёта (SPEC §13)."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.sandbox import SANDBOX_SOURCE
from app.models.auth import User
from app.models.kb import KbGap
from app.models.leads import Lead
from app.models.qualification import Escalation
from app.models.system import SystemAlert

# Расход за сутки — из единого учёта вызовов моделей (работа и тесты расходуют одни сутки).
SPENT_SINCE = text("SELECT coalesce(sum(cost_usd), 0) FROM llm_usage WHERE at >= :since")
SPENT_BY_PROVIDER = text(
    "SELECT provider, coalesce(sum(cost_usd), 0) AS usd FROM llm_usage "
    "WHERE at >= :since GROUP BY provider"
)
QUEUE_SIZE = text(
    "SELECT count(*) FROM procrastinate_jobs "
    "WHERE status = 'todo' AND (scheduled_at IS NULL OR scheduled_at <= now())"
)
FAILED_SINCE = text(
    """
    SELECT j.task_name, count(DISTINCT j.id) AS n
    FROM procrastinate_events e JOIN procrastinate_jobs j ON j.id = e.job_id
    WHERE e.type = 'failed' AND e.at >= :since
    GROUP BY j.task_name
    """
)
# Задачи, у которых последний успешный запуск позже последнего сбоя.
RECOVERED = text(
    """
    SELECT j.task_name
    FROM procrastinate_events e JOIN procrastinate_jobs j ON j.id = e.job_id
    WHERE j.task_name = ANY(:tasks) AND e.type IN ('failed', 'succeeded')
    GROUP BY j.task_name
    HAVING max(e.at) FILTER (WHERE e.type = 'succeeded')
        > coalesce(max(e.at) FILTER (WHERE e.type = 'failed'), '-infinity')
    """
)
TOP_GAPS = 3


@dataclass(frozen=True)
class DailyFigures:
    leads: int
    escalations: int
    open_escalations: int
    open_gaps: int
    cost_usd: float
    sla_overdue: int = 0
    take_median_s: float | None = None
    taken_by: tuple[tuple[str, int], ...] = ()
    top_gaps: tuple[str, ...] = ()


async def spent_since(session: AsyncSession, since: datetime) -> float:
    return float((await session.execute(SPENT_SINCE, {"since": since})).scalar_one() or 0.0)


async def spent_by_provider(session: AsyncSession, since: datetime) -> dict[str, float]:
    rows = (await session.execute(SPENT_BY_PROVIDER, {"since": since})).all()
    return {r.provider: float(r.usd) for r in rows if r.provider}


async def queue_size(session: AsyncSession) -> int:
    return int((await session.execute(QUEUE_SIZE)).scalar_one())


async def failed_tasks(session: AsyncSession, since: datetime) -> dict[str, int]:
    rows = (await session.execute(FAILED_SINCE, {"since": since})).all()
    return {r.task_name: int(r.n) for r in rows}


async def recovered_tasks(session: AsyncSession, tasks: set[str]) -> frozenset[str]:
    if not tasks:
        return frozenset()
    rows = (await session.execute(RECOVERED, {"tasks": sorted(tasks)})).all()
    return frozenset(r.task_name for r in rows)


async def alert_states(session: AsyncSession) -> dict[str, SystemAlert]:
    rows = (await session.scalars(select(SystemAlert).with_for_update())).all()
    return {r.key: r for r in rows}


async def daily_figures(session: AsyncSession, since: datetime) -> DailyFigures:
    async def count(stmt: Any) -> int:
        return int((await session.execute(stmt)).scalar_one())

    return DailyFigures(
        leads=await count(
            select(func.count())
            .select_from(Lead)
            .where(Lead.created_at >= since, Lead.source != SANDBOX_SOURCE)
        ),
        escalations=await count(
            select(func.count()).select_from(Escalation).where(Escalation.created_at >= since)
        ),
        open_escalations=await count(
            select(func.count())
            .select_from(Escalation)
            .where(Escalation.status.in_(("open", "snoozed")))
        ),
        open_gaps=await count(
            select(func.count()).select_from(KbGap).where(KbGap.status == "open")
        ),
        cost_usd=round(await spent_since(session, since), 2),
        sla_overdue=await count(
            select(func.count()).select_from(Escalation).where(Escalation.sla_notified_at >= since)
        ),
        take_median_s=await _take_median(session, since),
        taken_by=await _taken_by(session, since),
        top_gaps=await _top_gaps(session),
    )


async def _take_median(session: AsyncSession, since: datetime) -> float | None:
    seconds = func.extract("epoch", Escalation.taken_at - Escalation.created_at)
    stmt = select(func.percentile_cont(0.5).within_group(seconds)).where(
        Escalation.taken_at >= since
    )
    value = (await session.execute(stmt)).scalar_one_or_none()
    return float(value) if value is not None else None


async def _taken_by(session: AsyncSession, since: datetime) -> tuple[tuple[str, int], ...]:
    stmt = (
        select(User.full_name, func.count())
        .join(Escalation, Escalation.taken_by_user_id == User.id)
        .where(Escalation.taken_at >= since)
        .group_by(User.full_name)
        .order_by(func.count().desc(), User.full_name)
    )
    return tuple((name, int(n)) for name, n in (await session.execute(stmt)).all())


async def _top_gaps(session: AsyncSession) -> tuple[str, ...]:
    stmt = (
        select(KbGap.question)
        .where(KbGap.status == "open")
        .order_by(KbGap.occurrences.desc(), KbGap.id.desc())
        .limit(TOP_GAPS)
    )
    return tuple((await session.scalars(stmt)).all())
