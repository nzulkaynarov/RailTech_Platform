"""Дневной бюджет моделей (SPEC §11: `settings.budget`, BudgetGuard)."""

from collections.abc import Mapping
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


class Route(StrEnum):
    """Куда направить вызов модели с учётом лимитов (ADR-0014, Q-008)."""

    PRIMARY = "primary"
    FALLBACK = "fallback"
    UNAVAILABLE = "unavailable"  # честная передача человеку, без вызова


def provider_over(
    provider: str | None, spent: Mapping[str, float], limits: Mapping[str, float]
) -> bool:
    """Провайдер исчерпал дневной лимит. Неизвестный провайдер или лимит 0 — без ограничения."""
    if provider is None:
        return False
    limit = limits.get(provider, 0.0)
    return limit > 0 and spent.get(provider, 0.0) >= limit


def choose_route(
    *,
    primary_over: bool,
    fallback_over: bool,
    soft_over: bool,
    allows_fallback: bool,
    fallback_enabled: bool,
) -> Route:
    """Жёсткий лимит провайдера: диалог → резерв (если его провайдер в лимите), иначе отказ.

    Мягкий `daily_usd`: диалог → резерв, если он включён и в лимите; иначе остаёмся на основной.
    """
    fallback_ok = allows_fallback and not fallback_over
    if primary_over:
        return Route.FALLBACK if fallback_ok else Route.UNAVAILABLE
    if soft_over and fallback_ok and fallback_enabled:
        return Route.FALLBACK
    return Route.PRIMARY
