"""Дашборд (SPEC §10.1): воронка, эскалации по причинам, время до «Забрать», доля
fallback, стоимость моделей, пробелы KB, итоги прошлого периода, менеджеры и SLA.
Дневные агрегаты — материализованные представления; менеджеры и SLA — живые запросы
(`repositories/dashboard.py`)."""

from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.sandbox import SANDBOX_SOURCE
from app.models.kb import KbGap
from app.models.leads import Lead
from app.models.qualification import Escalation
from app.repositories import dashboard as repo
from app.schemas.admin import DailyStat, Dashboard, ManagerStat, SlaStat

VIEWS = ("mv_daily_stats", "mv_escalation_reasons")
# `mv_daily_stats` хранит 180 дней: прошлый период длиннее 90 дней был бы неполным.
MAX_PREVIOUS_DAYS = 90


async def refresh(session: AsyncSession) -> None:
    for view in VIEWS:
        await session.execute(text(f"REFRESH MATERIALIZED VIEW CONCURRENTLY {view}"))


async def build(
    session: AsyncSession,
    days: int,
    today: date,
    tz: str = "Asia/Tashkent",
    now: datetime | None = None,
) -> Dashboard:
    since = today - timedelta(days=days - 1)
    rows = await _daily_rows(session, since - timedelta(days=days))
    daily, before = split_period([_stat(r) for r in rows], since)
    since_at = datetime.combine(since, time(), ZoneInfo(tz))
    due, met = await repo.sla_counts(session, since_at, now or datetime.now(UTC))
    totals = _sum(daily, today)
    answered = totals.bot_answers + totals.fallbacks
    return Dashboard(
        days=days,
        funnel=await _funnel(session),
        totals=totals,
        previous=_sum(before, since - timedelta(days=1))
        if days <= MAX_PREVIOUS_DAYS and before
        else None,
        managers=merge_managers(await repo.manager_rows(session, since_at)),
        sla=sla_stat(due, met),
        daily=daily,
        escalation_reasons=await _reasons(session, since),
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


async def _daily_rows(session: AsyncSession, since: date) -> Any:
    stmt = text("SELECT * FROM mv_daily_stats WHERE day >= :since ORDER BY day")
    return (await session.execute(stmt, {"since": since})).mappings().all()


async def _reasons(session: AsyncSession, since: date) -> dict[str, int]:
    stmt = text(
        "SELECT code, sum(n)::int AS n FROM mv_escalation_reasons "
        "WHERE day >= :since GROUP BY code ORDER BY n DESC"
    )
    return {code: int(n) for code, n in (await session.execute(stmt, {"since": since})).all()}


async def _funnel(session: AsyncSession) -> dict[str, int]:
    stmt = (
        select(Lead.stage, func.count())
        .where(Lead.erased_at.is_(None), Lead.source != SANDBOX_SOURCE)
        .group_by(Lead.stage)
    )
    return {stage: int(n) for stage, n in (await session.execute(stmt)).all()}


def split_period(daily: list[DailyStat], since: date) -> tuple[list[DailyStat], list[DailyStat]]:
    """Дни выбранного периода и дни прошлого периода той же длины (строки уже отобраны)."""
    return [d for d in daily if d.day >= since], [d for d in daily if d.day < since]


def sla_stat(due: int, met: int) -> SlaStat:
    return SlaStat(due=due, met=met, share=round(met / due, 4) if due else None)


def merge_managers(rows: dict[str, list[Any]]) -> list[ManagerStat]:
    """Склейка срезов по пользователю; порядок — больше забрал, затем больше ведёт."""
    names = {int(r["id"]): str(r["full_name"]) for r in rows["names"]}
    taken = {int(r["user_id"]): r for r in rows["taken"]}
    won = {int(r["user_id"]): int(r["won"]) for r in rows["won"]}
    active = {int(r["user_id"]): int(r["active"]) for r in rows["active"]}
    out = []
    for uid in sorted(set(taken) | set(won) | set(active)):
        median = taken[uid]["median_min"] if uid in taken else None
        out.append(
            ManagerStat(
                user_id=uid,
                name=names.get(uid, f"#{uid}"),
                taken=int(taken[uid]["taken"]) if uid in taken else 0,
                median_take_minutes=round(float(median), 1) if median is not None else None,
                won=won.get(uid, 0),
                active_leads=active.get(uid, 0),
            )
        )
    return sorted(out, key=lambda m: (-m.taken, -m.active_leads, m.name))


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
