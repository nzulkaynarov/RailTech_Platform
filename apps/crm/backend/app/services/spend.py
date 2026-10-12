"""Экран «Расходы»: сегодня против лимитов, ряд по дням, срезы и стоимость лида (llm_usage)."""

from collections.abc import Mapping
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.budget import day_start
from app.models.leads import Lead
from app.repositories import monitoring as monitoring_repo
from app.repositories import spend as repo
from app.schemas.settings import AppSettings
from app.schemas.spend import LeadSpend, ProviderToday, SpendDay, SpendReport, SpendSlice

TOP_LEADS = 10


def series(today: date, days: int, by_day: Mapping[date, Mapping[str, float]]) -> list[SpendDay]:
    """Непрерывный ряд за `days` суток, пустые сутки — нули (график без дыр)."""
    out: list[SpendDay] = []
    for offset in range(days - 1, -1, -1):
        day = today - timedelta(days=offset)
        values = by_day.get(day, {})
        out.append(
            SpendDay(
                day=day,
                work_usd=round(values.get("work", 0.0), 4),
                test_usd=round(values.get("test", 0.0), 4),
            )
        )
    return out


def provider_rows(limits: Mapping[str, float], spent: Mapping[str, float]) -> list[ProviderToday]:
    names = sorted(set(limits) | set(spent))
    return [
        ProviderToday(
            provider=name,
            spent_usd=round(spent.get(name, 0.0), 4),
            limit_usd=limits.get(name, 0.0),
        )
        for name in names
    ]


async def build(session: AsyncSession, cfg: AppSettings, days: int, now: datetime) -> SpendReport:
    tz = cfg.business_hours.timezone
    today_start = day_start(now, tz)
    since = today_start - timedelta(days=days - 1)
    leads = await repo.per_lead(session, since)
    lead_total = sum(usd for _, usd, _ in leads)
    by_kind = await repo.grouped(session, since, "kind")
    top = leads[:TOP_LEADS]
    names = await _lead_names(session, [lead_id for lead_id, _, _ in top])
    return SpendReport(
        days=days,
        today_usd=round(await monitoring_repo.spent_since(session, today_start), 4),
        daily_usd=cfg.budget.daily_usd,
        providers=provider_rows(
            cfg.budget.providers.model_dump(),
            await monitoring_repo.spent_by_provider(session, today_start),
        ),
        series=series(
            now.astimezone(ZoneInfo(tz)).date(), days, await repo.daily(session, since, tz)
        ),
        by_purpose=_slices(await repo.grouped(session, since, "purpose")),
        by_kind=_slices(by_kind),
        total_usd=round(sum(usd for _, usd, _ in by_kind), 4),
        leads=len(leads),
        avg_per_lead_usd=round(lead_total / len(leads), 4) if leads else 0.0,
        top_leads=[
            LeadSpend(
                lead_id=lead_id, lead_name=names.get(lead_id), cost_usd=round(usd, 4), calls=n
            )
            for lead_id, usd, n in top
        ],
    )


def _slices(rows: list[tuple[str, float, int]]) -> list[SpendSlice]:
    return [SpendSlice(key=key, cost_usd=round(usd, 4), calls=n) for key, usd, n in rows]


async def _lead_names(session: AsyncSession, ids: list[int]) -> dict[int, str]:
    """Имена лидов для «Топ лидов по расходу» — вместо голых номеров."""
    if not ids:
        return {}
    rows = await session.execute(select(Lead.id, Lead.display_name).where(Lead.id.in_(ids)))
    return {lead_id: name for lead_id, name in rows.tuples().all() if name}
