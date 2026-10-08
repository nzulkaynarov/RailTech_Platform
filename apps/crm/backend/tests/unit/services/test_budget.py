from typing import cast

import pytest

from app.services.budget import BudgetedModel, BudgetGuard
from tests.unit.agents.fakes import ReplayModel, reply


class StubGuard:
    def __init__(self, over: bool) -> None:
        self.over = over

    async def fallback_required(self) -> bool:
        return self.over


@pytest.mark.parametrize(("over", "expected"), [(False, "primary"), (True, "fallback")])
async def test_budgeted_model_routes_dialog(over: bool, expected: str) -> None:
    primary, fallback = ReplayModel(reply("primary")), ReplayModel(reply("fallback"))
    model = BudgetedModel(primary, fallback, cast(BudgetGuard, StubGuard(over)))
    result = await model.complete([{"role": "user", "content": "hi"}])
    assert result.text == expected
