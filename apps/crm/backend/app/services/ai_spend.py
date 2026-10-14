"""Расходы на ИИ по ансамблю (M3-CRM-09): журнал LiteLLM → «Расходы» и «Состояние системы».

Источник — HTTP API LiteLLM (`integrations/litellm_spend`), а не `llm_usage` CRM: в шлюз ходят
CRM и ERP, и цифры должны совпадать с журналом прокси до вызова. Свёртка — `domain/ai_spend`.
Бюджет на день по системе: CRM — `settings.budget.daily_usd`, ERP — `settings.budget.erp_daily_usd`
(CRM расход ERP не ограничивает — показывает). Кэш 60 с на период; сбой шлюза на «Расходах» —
ошибка 502 `litellm_unavailable`, на «Состоянии системы» — «нет данных».
"""

import asyncio
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo

import structlog

from app.domain import ai_spend as rules
from app.domain.ai_spend import Agg, Cube
from app.domain.errors import Reason, UpstreamUnavailableError, ValidationFailedError
from app.domain.system_status import AiBudgetFacts
from app.integrations.litellm_spend import LiteLLMSpendError, SpendLogs
from app.schemas.ai_spend import (
    AiBudgetOverrun,
    AiSpendGroup,
    AiSpendReport,
    AiSpendRow,
    AiSpendSystemCost,
    AiSpendTotals,
    AiSystemBudget,
)
from app.schemas.settings import AppSettings
from app.services.settings import SettingsService

logger = structlog.get_logger(__name__)
DEFAULT_DAYS = 30
TODAY_TIMEOUT_S = 5.0
USD_DIGITS = 10


class SpendLogSource(Protocol):
    async def fetch(self, start: datetime, end: datetime) -> SpendLogs: ...


@dataclass(frozen=True, slots=True)
class Snapshot:
    cube: Cube
    truncated: bool
    fetched_at: datetime


class AiSpendService:
    def __init__(
        self,
        source: SpendLogSource,
        settings: SettingsService,
        ttl_s: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._source = source
        self._settings = settings
        self._ttl_s = ttl_s
        self._clock = clock
        self._now = now
        self._cache: dict[tuple[date, date], tuple[float, Snapshot]] = {}
        self._today: tuple[float, list[AiBudgetFacts] | None] | None = None

    async def report(
        self, first: date | None, last: date | None, group: AiSpendGroup
    ) -> AiSpendReport:
        cfg = await self._settings.get()
        tz = cfg.business_hours.timezone
        today = self._now().astimezone(ZoneInfo(tz)).date()
        last = last or today
        first = first or last - timedelta(days=DEFAULT_DAYS - 1)
        problem = rules.period_error(first, last, today)
        if problem is not None:
            raise ValidationFailedError(problem, reason=Reason.AI_SPEND_PERIOD, field="from")
        period = await self._snapshot(first, last, tz)
        today_cube = period.cube if last == today else (await self._snapshot(today, today, tz)).cube
        return assemble(period, today_cube, today, group, tz, budgets(cfg))

    async def today_facts(self) -> list[AiBudgetFacts] | None:
        """Расход сегодня против бюджета по системам; None — журнал шлюза недоступен."""
        cached = self._today
        if cached is not None and self._clock() < cached[0]:
            return cached[1]
        facts: list[AiBudgetFacts] | None
        try:
            facts = await asyncio.wait_for(self._today_facts(), TODAY_TIMEOUT_S)
        except Exception as exc:  # noqa: BLE001 — «Состояние системы» не падает из-за журнала
            logger.warning("ai_spend_today_unavailable", error=type(exc).__name__)
            facts = None
        self._today = (self._clock() + self._ttl_s, facts)
        return facts

    async def _today_facts(self) -> list[AiBudgetFacts]:
        cfg = await self._settings.get()
        tz = cfg.business_hours.timezone
        today = self._now().astimezone(ZoneInfo(tz)).date()
        cube = (await self._snapshot(today, today, tz)).cube
        spent = {s: rules.combine(d.values()).cost_usd for s, d in _per_system(cube).items()}
        limits = budgets(cfg)
        return [
            AiBudgetFacts(system, _usd(spent.get(system, 0.0)), limits.get(system, 0.0))
            for system in rules.systems_order(spent)
        ]

    async def _snapshot(self, first: date, last: date, tz: str) -> Snapshot:
        now = self._clock()
        self._cache = {k: v for k, v in self._cache.items() if v[0] > now}
        cached = self._cache.get((first, last))
        if cached is not None:
            return cached[1]
        start, end = rules.window(first, last, tz)
        try:
            logs = await self._source.fetch(start, end)
        except LiteLLMSpendError as exc:
            raise UpstreamUnavailableError(
                "litellm spend logs unavailable", reason=Reason.LITELLM_UNAVAILABLE
            ) from exc
        rows = [row for raw in logs.rows if (row := rules.to_row(raw)) is not None]
        snapshot = Snapshot(rules.build_cube(rows, first, last, tz), logs.truncated, self._now())
        if logs.truncated:
            logger.warning("ai_spend_truncated", first=str(first), last=str(last))
        self._cache[(first, last)] = (self._clock() + self._ttl_s, snapshot)
        return snapshot


def budgets(cfg: AppSettings) -> dict[str, float]:
    return {"crm": cfg.budget.daily_usd, "erp": cfg.budget.erp_daily_usd}


def assemble(
    period: Snapshot,
    today_cube: Cube,
    today: date,
    group: AiSpendGroup,
    tz: str,
    limits: Mapping[str, float],
) -> AiSpendReport:
    cube = period.cube
    per_system = _per_system(cube)
    today_per_system = _per_system(today_cube)
    systems = [
        _system(name, per_system.get(name, {}), today_per_system.get(name, {}), today, limits)
        for name in rules.systems_order([*per_system, *today_per_system])
    ]
    return AiSpendReport(
        date_from=cube.first,
        date_to=cube.last,
        group=group,
        timezone=tz,
        rows=[_row(key, agg, split) for key, agg, split in rules.group(cube, group)],
        totals=AiSpendTotals(**_numbers(rules.total(cube))),
        systems=systems,
        overruns=_overruns(per_system, limits),
        erp_connected=any(a.calls for a in per_system.get("erp", {}).values()),
        truncated=period.truncated,
        fetched_at=period.fetched_at,
    )


def _per_system(cube: Cube) -> dict[str, dict[date, Agg]]:
    return rules.by_system_day(cube)


def _system(
    name: str,
    days: Mapping[date, Agg],
    today_days: Mapping[date, Agg],
    today: date,
    limits: Mapping[str, float],
) -> AiSystemBudget:
    limit = limits.get(name, 0.0)
    period = rules.combine(days.values())
    now = today_days.get(today, Agg())
    return AiSystemBudget(
        system=name,
        daily_usd=limit,
        today_usd=_usd(now.cost_usd),
        today_calls=now.calls,
        over_today=rules.over_budget(now.cost_usd, limit),
        period_usd=_usd(period.cost_usd),
        period_calls=period.calls,
        fallback_calls=period.fallback_calls,
        days_over=sum(1 for a in days.values() if rules.over_budget(a.cost_usd, limit)),
        connected=period.calls > 0,
    )


def _overruns(
    per_system: Mapping[str, Mapping[date, Agg]], limits: Mapping[str, float]
) -> list[AiBudgetOverrun]:
    out = [
        AiBudgetOverrun(system=name, day=day, cost_usd=_usd(agg.cost_usd), daily_usd=limits[name])
        for name, days in per_system.items()
        if name in limits
        for day, agg in days.items()
        if rules.over_budget(agg.cost_usd, limits[name])
    ]
    return sorted(out, key=lambda o: (o.day, o.system), reverse=True)


def _usd(value: float) -> float:
    """Без округления до центов: цифры сверяются с журналом LiteLLM до вызова; срезаем шум float."""
    return round(value, USD_DIGITS)


def _numbers(agg: Agg) -> dict[str, int | float]:
    return {
        "calls": agg.calls,
        "failed_calls": agg.failed_calls,
        "input_tokens": agg.input_tokens,
        "output_tokens": agg.output_tokens,
        "cost_usd": _usd(agg.cost_usd),
        "fallback_calls": agg.fallback_calls,
    }


def _row(key: str, agg: Agg, split: Mapping[str, Agg]) -> AiSpendRow:
    return AiSpendRow(
        key=key,
        **_numbers(agg),
        by_system=[
            AiSpendSystemCost(system=s, cost_usd=_usd(split[s].cost_usd), calls=split[s].calls)
            for s in rules.systems_order(split)
            if s in split
        ],
    )
