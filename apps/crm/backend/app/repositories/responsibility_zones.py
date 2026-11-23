"""Доступ к реестру зон ответственности."""

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.responsibility_zones import ResponsibilityZone


async def list_zones(session: AsyncSession) -> Sequence[ResponsibilityZone]:
    return (await session.scalars(select(ResponsibilityZone).order_by(ResponsibilityZone.id))).all()


async def get(
    session: AsyncSession, zone_id: int, *, for_update: bool = False
) -> ResponsibilityZone | None:
    stmt = select(ResponsibilityZone).where(ResponsibilityZone.id == zone_id)
    if for_update:
        stmt = stmt.with_for_update()
    return (await session.scalars(stmt)).first()


async def by_code(session: AsyncSession, code: str) -> ResponsibilityZone | None:
    stmt = select(ResponsibilityZone).where(ResponsibilityZone.code == code)
    return (await session.scalars(stmt)).first()
