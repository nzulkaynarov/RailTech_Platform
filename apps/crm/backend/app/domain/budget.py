"""Дневной бюджет моделей (SPEC §11: `settings.budget`, BudgetGuard)."""

from datetime import datetime
from enum import StrEnum
from zoneinfo import ZoneInfo


class BudgetState(StrEnum):
    OK = "ok"
    WARN = "warn"  # > 80 % — алерт в канал
    OVER = "over"  # ≥ 100 % — диалог на fallback-model, квалификатор продолжает


def budget_state(spent_usd: float, daily_usd: float, warn_share: float = 0.8) -> BudgetState:
    """`daily_usd == 0` — лимит не задан."""
    if daily_usd <= 0:
        return BudgetState.OK
    share = spent_usd / daily_usd
    if share >= 1:
        return BudgetState.OVER
    return BudgetState.WARN if share > warn_share else BudgetState.OK


def use_fallback(state: BudgetState, fallback_enabled: bool) -> bool:
    return state is BudgetState.OVER and fallback_enabled


def day_start(now: datetime, timezone: str) -> datetime:
    """Начало текущих суток в часовом поясе компании (бюджет и отчёт — по Ташкенту)."""
    local = now.astimezone(ZoneInfo(timezone))
    return local.replace(hour=0, minute=0, second=0, microsecond=0)
