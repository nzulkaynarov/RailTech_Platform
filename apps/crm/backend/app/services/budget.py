"""BudgetGuard (SPEC §11): при превышении дневного бюджета диалог → fallback-model.

Квалификатор продолжает на своей модели. Расход — из `cost_usd` ходов и прогонов
квалификатора (заголовок LiteLLM), кэш на минуту, чтобы не считать на каждом ходе.
"""

import time
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.llm import ChatCompleter, ChatResult
from app.domain.budget import BudgetState, budget_state, day_start, use_fallback
from app.repositories import monitoring as repo
from app.services.settings import SettingsService

logger = structlog.get_logger(__name__)


class BudgetGuard:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        settings: SettingsService,
        ttl_s: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._sessions = sessions
        self._settings = settings
        self._ttl_s = ttl_s
        self._clock = clock
        self._cached: tuple[float, bool] | None = None

    async def state(self, now: datetime | None = None) -> BudgetState:
        cfg = await self._settings.get()
        since = day_start(now or datetime.now(UTC), cfg.business_hours.timezone)
        async with self._sessions() as session:
            spent = await repo.spent_since(session, since)
        return budget_state(spent, cfg.budget.daily_usd)

    async def fallback_required(self) -> bool:
        cached = self._cached
        if cached is not None and self._clock() < cached[0]:
            return cached[1]
        cfg = await self._settings.get()
        required = use_fallback(await self.state(), cfg.budget.fallback_model_enabled)
        if required:
            logger.warning("budget_exceeded_dialog_on_fallback", daily_usd=cfg.budget.daily_usd)
        self._cached = (self._clock() + self._ttl_s, required)
        return required


class BudgetedModel:
    """ChatCompleter диалога: обычная модель, а при исчерпанном бюджете — fallback."""

    def __init__(self, primary: ChatCompleter, fallback: ChatCompleter, guard: BudgetGuard) -> None:
        self._primary = primary
        self._fallback = fallback
        self._guard = guard

    async def complete(
        self,
        messages: Sequence[dict[str, Any]],
        *,
        tools: Sequence[dict[str, Any]] | None = None,
        response_format: dict[str, Any] | None = None,
        name: str = "llm",
    ) -> ChatResult:
        model = self._fallback if await self._guard.fallback_required() else self._primary
        return await model.complete(
            messages, tools=tools, response_format=response_format, name=name
        )
