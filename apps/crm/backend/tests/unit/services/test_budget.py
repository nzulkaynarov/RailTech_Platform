from datetime import datetime
from typing import Any, cast

import pytest

from app.agents.llm import LlmUnavailableError
from app.domain.budget import Route
from app.schemas.settings import AppSettings
from app.services.budget import BudgetedModel, BudgetGuard, Spend
from tests.unit.agents.fakes import ReplayModel, reply


class StubGuard:
    def __init__(self, route: Route) -> None:
        self.decision = route
        self.calls: list[tuple[str, bool]] = []

    async def route(self, alias: str, *, allows_fallback: bool) -> Route:
        self.calls.append((alias, allows_fallback))
        return self.decision


@pytest.mark.parametrize(
    ("route", "expected"),
    [(Route.PRIMARY, "primary"), (Route.FALLBACK, "fallback")],
)
async def test_budgeted_model_routes_dialog(route: Route, expected: str) -> None:
    primary, fallback = ReplayModel(reply("primary")), ReplayModel(reply("fallback"))
    model = BudgetedModel(primary, fallback, cast(BudgetGuard, StubGuard(route)))
    result = await model.complete([{"role": "user", "content": "hi"}])
    assert result.text == expected


async def test_unavailable_raises_without_calling_model() -> None:
    primary = ReplayModel(reply("primary"))
    model = BudgetedModel(primary, None, cast(BudgetGuard, StubGuard(Route.UNAVAILABLE)))
    with pytest.raises(LlmUnavailableError):
        await model.complete([])


class FixedSettings:
    async def get(self) -> AppSettings:
        return AppSettings()  # daily_usd 2, anthropic 3, gemini 1


class FixedCatalog:
    async def provider(self, alias: str) -> str | None:
        return {"dialog-model": "anthropic", "fallback-model": "gemini"}.get(alias)


CATALOG = FixedCatalog()


class SpendGuard(BudgetGuard):
    def __init__(self, spend: Spend, catalog: FixedCatalog | None = CATALOG) -> None:
        super().__init__(cast(Any, None), cast(Any, FixedSettings()), catalog)
        self._spend = spend

    async def spend(self, now: datetime | None = None) -> Spend:
        return self._spend


@pytest.mark.parametrize(
    ("total", "by_provider", "allows_fallback", "expected"),
    [
        (0.5, {"anthropic": 0.5}, True, Route.PRIMARY),
        (2.0, {"anthropic": 2.0}, True, Route.FALLBACK),  # мягкий бюджет
        (2.0, {"anthropic": 2.0}, False, Route.PRIMARY),
        (3.2, {"anthropic": 3.0, "gemini": 0.2}, True, Route.FALLBACK),
        (4.0, {"anthropic": 3.0, "gemini": 1.0}, True, Route.UNAVAILABLE),
        (3.0, {"anthropic": 3.0}, False, Route.UNAVAILABLE),
    ],
)
async def test_guard_routes_by_ledger(
    total: float, by_provider: dict[str, float], allows_fallback: bool, expected: Route
) -> None:
    guard = SpendGuard(Spend(total, by_provider))
    assert await guard.route("dialog-model", allows_fallback=allows_fallback) is expected


async def test_unknown_provider_skips_provider_limits() -> None:
    guard = SpendGuard(Spend(0.1, {"anthropic": 50.0}), catalog=None)
    assert await guard.route("dialog-model", allows_fallback=False) is Route.PRIMARY


async def test_role_without_fallback_never_asks_for_it() -> None:
    guard = StubGuard(Route.PRIMARY)
    primary = ReplayModel(reply("ok"))
    model = BudgetedModel(primary, None, cast(BudgetGuard, guard), alias="qualifier-model")
    assert (await model.complete([])).text == "ok"
    assert guard.calls == [("qualifier-model", False)]
