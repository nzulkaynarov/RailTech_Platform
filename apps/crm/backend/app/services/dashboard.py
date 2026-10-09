"""Дашборд (SPEC §10.1): воронка, эскалации по причинам, время до «Забрать», доля
fallback, стоимость моделей, пробелы KB. Агрегаты — материализованные представления."""

from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.kb import KbGap
from app.models.leads import Lead
from app.models.qualification import Escalation
from app.schemas.admin import DailyStat, Dashboard

VIEWS = ("mv_daily_stats", "mv_escalation_reasons")


async def refresh(session: AsyncSession) -> None:
    for view in VIEWS:
        await session.execute(text(f"REFRESH MATERIALIZED VIEW CONCURRENTLY {view}"))


async def build(session: AsyncSession, days: int, today: date) -> Dashboard:
    since = today - timedelta(days=days - 1)
    rows = (
        (
            await session.execute(
                text("SELECT * FROM mv_daily_stats WHERE day >= :since ORDER BY day"),
                {"since": since},
            )
        )
        .mappings()
        .all()
    )
    daily = [_stat(r) for r in rows]
    reasons = (
        await session.execute(
            text(
                "SELECT code, sum(n)::int AS n FROM mv_escalation_reasons "
                "WHERE day >= :since GROUP BY code ORDER BY n DESC"
            ),
            {"since": since},
        )
    ).all()
    funnel_rows = (
        await session.execute(
            select(Lead.stage, func.count()).where(Lead.erased_at.is_(None)).group_by(Lead.stage)
        )
    ).all()
    totals = _sum(daily, today)
    answered = totals.bot_answers + totals.fallbacks
    return Dashboard(
        days=days,
        funnel={stage: int(n) for stage, n in funnel_rows},
        totals=totals,
        daily=daily,
        escalation_reasons={code: int(n) for code, n in reasons},
        fallback_share=round(totals.fallbacks / answered, 4) if answered else None,
        open_gaps=await _count(
            session, select(func.count()).select_from(KbGap).where(KbGap.status == "open")
        ),
        open_escalations=await _count(
            session,
            select(func.count())
            .select_from(Escalation)
            .where(Escalation.status.in_(("open", "snoozed"))),
        ),
        refreshed_at=_refreshed(rows),
    )


def _stat(row: Any) -> DailyStat:
    return DailyStat(
        day=row["day"],
        leads_created=row["leads_created"],
        escalations=row["escalations"],
        taken=row["taken"],
        won=row["won"],
        lost=row["lost"],
        bot_answers=row["bot_answers"],
        fallbacks=row["fallbacks"],
        avg_take_minutes=round(row["avg_take_minutes"], 1)
        if row["avg_take_minutes"] is not None
        else None,
        cost_usd=round(row["cost_usd"], 4),
    )


def _sum(daily: list[DailyStat], today: date) -> DailyStat:
    takes = [
        (d.avg_take_minutes, d.taken) for d in daily if d.avg_take_minutes is not None and d.taken
    ]
    weight = sum(n for _, n in takes)
    return DailyStat(
        day=today,
        leads_created=sum(d.leads_created for d in daily),
        escalations=sum(d.escalations for d in daily),
        taken=sum(d.taken for d in daily),
        won=sum(d.won for d in daily),
        lost=sum(d.lost for d in daily),
        bot_answers=sum(d.bot_answers for d in daily),
        fallbacks=sum(d.fallbacks for d in daily),
        avg_take_minutes=round(sum(m * n for m, n in takes) / weight, 1) if weight else None,
        cost_usd=round(sum(d.cost_usd for d in daily), 4),
    )


def _refreshed(rows: Any) -> datetime | None:
    return rows[-1]["refreshed_at"] if rows else None


async def _count(session: AsyncSession, stmt: Any) -> int:
    return int(await session.scalar(stmt) or 0)
