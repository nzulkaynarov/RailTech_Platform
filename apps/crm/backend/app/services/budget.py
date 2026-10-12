"""BudgetGuard (SPEC §11, ADR-0014, Q-008): лимиты расходов на модели перед вызовом.

- Мягкий `settings.budget.daily_usd`: диалог → fallback-model, квалификатор продолжает.
- Дневной лимит провайдера `settings.budget.providers`: диалог → fallback-model, если провайдер
  резерва в лимите, иначе отказ (`LlmUnavailableError` → бот честно передаёт человеку);
  квалификатор и прочие роли — отказ.

Расход — из единого учёта `llm_usage` за сутки по Ташкенту, кэш на минуту. Провайдер алиаса —
из каталога LiteLLM (`/model/info`); неизвестен → лимит провайдера не применяется.
"""

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.llm import FALLBACK, ChatCompleter, ChatResult, LlmUnavailableError
from app.domain.budget import (
    BudgetState,
    Route,
    budget_state,
    choose_route,
    day_start,
    provider_over,
    use_fallback,
)
from app.repositories import monitoring as repo
from app.services.settings import SettingsService

logger = structlog.get_logger(__name__)


class ProviderResolver(Protocol):
    async def provider(self, alias: str) -> str | None: ...


@dataclass(frozen=True, slots=True)
class Spend:
    total: float
    by_provider: dict[str, float]


class BudgetGuard:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        settings: SettingsService,
        catalog: ProviderResolver | None = None,
        ttl_s: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._sessions = sessions
        self._settings = settings
        self._catalog = catalog
        self._ttl_s = ttl_s
        self._clock = clock
        self._cached: tuple[float, Spend] | None = None

    async def spend(self, now: datetime | None = None) -> Spend:
        cached = self._cached
        if now is None and cached is not None and self._clock() < cached[0]:
            return cached[1]
        cfg = await self._settings.get()
        since = day_start(now or datetime.now(UTC), cfg.business_hours.timezone)
        async with self._sessions() as session:
            spend = Spend(
                total=await repo.spent_since(session, since),
                by_provider=await repo.spent_by_provider(session, since),
            )
        self._cached = (self._clock() + self._ttl_s, spend)
        return spend

    async def state(self, now: datetime | None = None) -> BudgetState:
        cfg = await self._settings.get()
        return budget_state((await self.spend(now)).total, cfg.budget.daily_usd)

    async def fallback_required(self) -> bool:
        """Только мягкий бюджет (совместимость монитора/тестов)."""
        cfg = await self._settings.get()
        return use_fallback(await self.state(), cfg.budget.fallback_model_enabled)

    async def route(self, alias: str, *, allows_fallback: bool) -> Route:
        cfg = await self._settings.get()
        spend = await self.spend()
        limits = cfg.budget.providers.model_dump()
        primary = await self._provider(alias)
        fallback = await self._provider(FALLBACK)
        decision = choose_route(
            primary_over=provider_over(primary, spend.by_provider, limits),
            fallback_over=provider_over(fallback, spend.by_provider, limits),
            soft_over=budget_state(spend.total, cfg.budget.daily_usd) is BudgetState.OVER,
            allows_fallback=allows_fallback,
            fallback_enabled=cfg.budget.fallback_model_enabled,
        )
        if decision is not Route.PRIMARY:
            logger.warning("budget_route", alias=alias, provider=primary, route=decision.value)
        return decision

    async def _provider(self, alias: str) -> str | None:
        return await self._catalog.provider(alias) if self._catalog else None


class BudgetedModel:
    """ChatCompleter под бюджетом: основная модель, резерв или честный отказ.

    `fallback=None` — роль без резерва (квалификатор): сверх лимита провайдера — отказ.
    """

    def __init__(
        self,
        primary: ChatCompleter,
        fallback: ChatCompleter | None,
        guard: BudgetGuard,
        alias: str = "dialog-model",
    ) -> None:
        self._primary = primary
        self._fallback = fallback
        self._guard = guard
        self._alias = alias

    async def complete(
        self,
        messages: Sequence[dict[str, Any]],
        *,
        tools: Sequence[dict[str, Any]] | None = None,
        response_format: dict[str, Any] | None = None,
        name: str = "llm",
    ) -> ChatResult:
        decision = await self._guard.route(self._alias, allows_fallback=self._fallback is not None)
        if decision is Route.UNAVAILABLE:
            raise LlmUnavailableError(self._alias)
        model = self._fallback if decision is Route.FALLBACK and self._fallback else self._primary
        return await model.complete(
            messages, tools=tools, response_format=response_format, name=name
        )
