"""Чтение журнала решений по лиду."""

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.qualification import QualifierRun, StageTransition


async def qualifier_runs(session: AsyncSession, lead_id: int, limit: int) -> Sequence[QualifierRun]:
    stmt = (
        select(QualifierRun)
        .where(QualifierRun.lead_id == lead_id)
        .order_by(QualifierRun.id.desc())
        .limit(limit)
    )
    return (await session.scalars(stmt)).all()


async def transitions(session: AsyncSession, lead_id: int, limit: int) -> Sequence[StageTransition]:
    stmt = (
        select(StageTransition)
        .where(StageTransition.lead_id == lead_id)
        .order_by(StageTransition.id.desc())
        .limit(limit)
    )
    return (await session.scalars(stmt)).all()
