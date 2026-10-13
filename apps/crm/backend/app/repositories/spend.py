"""Агрегаты учёта вызовов моделей `llm_usage` для экрана «Расходы»."""

from datetime import date, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

DAILY = text(
    """
    SELECT (at AT TIME ZONE :tz)::date AS day, kind, sum(cost_usd) AS usd
    FROM llm_usage WHERE at >= :since GROUP BY 1, 2
    """
)
BY_COLUMN = {
    col: text(
        f"SELECT {col} AS key, sum(cost_usd) AS usd, count(*) AS n FROM llm_usage "  # noqa: S608
        f"WHERE at >= :since GROUP BY {col} ORDER BY usd DESC"
    )
    for col in ("purpose", "kind", "alias")
}
LEADS = text(
    """
    SELECT lead_id, sum(cost_usd) AS usd, count(*) AS n FROM llm_usage
    WHERE at >= :since AND lead_id IS NOT NULL AND kind = 'work'
    GROUP BY lead_id ORDER BY usd DESC
    """
)


async def daily(session: AsyncSession, since: datetime, tz: str) -> dict[date, dict[str, float]]:
    rows = (await session.execute(DAILY, {"since": since, "tz": tz})).all()
    out: dict[date, dict[str, float]] = {}
    for r in rows:
        out.setdefault(r.day, {})[r.kind] = float(r.usd or 0.0)
    return out


async def grouped(
    session: AsyncSession, since: datetime, column: str
) -> list[tuple[str, float, int]]:
    rows = (await session.execute(BY_COLUMN[column], {"since": since})).all()
    return [(str(r.key), float(r.usd or 0.0), int(r.n)) for r in rows]


async def per_lead(session: AsyncSession, since: datetime) -> list[tuple[int, float, int]]:
    rows = (await session.execute(LEADS, {"since": since})).all()
    return [(int(r.lead_id), float(r.usd or 0.0), int(r.n)) for r in rows]
