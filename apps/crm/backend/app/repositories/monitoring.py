"""Метрики эксплуатации для монитора и дневного отчёта (SPEC §13)."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.kb import KbGap
from app.models.leads import Lead
from app.models.qualification import Escalation
from app.models.system import SystemAlert

SPENT_SINCE = text(
    """
    SELECT coalesce((SELECT sum((meta->>'cost_usd')::double precision) FROM messages
                     WHERE role = 'bot' AND created_at >= :since), 0)
         + coalesce((SELECT sum(cost_usd) FROM qualifier_runs WHERE created_at >= :since), 0)
    """
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


@dataclass(frozen=True)
class DailyFigures:
    leads: int
    escalations: int
    open_escalations: int
    open_gaps: int
    cost_usd: float


async def spent_since(session: AsyncSession, since: datetime) -> float:
    return float((await session.execute(SPENT_SINCE, {"since": since})).scalar_one() or 0.0)


async def queue_size(session: AsyncSession) -> int:
    return int((await session.execute(QUEUE_SIZE)).scalar_one())


async def failed_tasks(session: AsyncSession, since: datetime) -> dict[str, int]:
    rows = (await session.execute(FAILED_SINCE, {"since": since})).all()
    return {r.task_name: int(r.n) for r in rows}


async def alert_states(session: AsyncSession) -> dict[str, SystemAlert]:
    rows = (await session.scalars(select(SystemAlert).with_for_update())).all()
    return {r.key: r for r in rows}


async def daily_figures(session: AsyncSession, since: datetime) -> DailyFigures:
    async def count(stmt: Any) -> int:
        return int((await session.execute(stmt)).scalar_one())

    return DailyFigures(
        leads=await count(select(func.count()).select_from(Lead).where(Lead.created_at >= since)),
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
    )
