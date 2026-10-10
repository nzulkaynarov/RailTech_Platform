from datetime import UTC, datetime, timedelta

import pytest

from app.domain.alerts import (
    AlertState,
    Check,
    Decision,
    HealthSnapshot,
    checks,
    decide,
    message,
    model_probe_due,
    provider_problem,
)
from app.domain.budget import BudgetState, budget_state, day_start, use_fallback

NOW = datetime(2026, 10, 8, 10, 0, tzinfo=UTC)
MIN = timedelta(minutes=1)


def active(snapshot: HealthSnapshot, known: set[str] | None = None) -> set[str]:
    return {c.key for c in checks(snapshot, known or set()) if c.active}


@pytest.mark.parametrize(
    ("snapshot", "expected"),
    [
        (HealthSnapshot(), set()),
        (HealthSnapshot(queue_size=100), set()),
        (HealthSnapshot(queue_size=101), {"queue_size"}),
        (HealthSnapshot(litellm_ok=False), {"litellm_down"}),
        (HealthSnapshot(spent_usd=8.0, daily_budget_usd=10.0), set()),
        (HealthSnapshot(spent_usd=8.01, daily_budget_usd=10.0), {"budget"}),
        (HealthSnapshot(spent_usd=500.0, daily_budget_usd=0.0), set()),
        (HealthSnapshot(failed_tasks={"qualify_lead": 2}), {"failed_task:qualify_lead"}),
        (
            HealthSnapshot(models={"dialog-model": "нет кредитов", "fallback-model": None}),
            {"model:dialog-model"},
        ),
    ],
)
def test_checks(snapshot: HealthSnapshot, expected: set[str]) -> None:
    assert active(snapshot) == expected


def test_known_failed_task_gets_inactive_check_to_resolve() -> None:
    keys = {c.key: c.active for c in checks(HealthSnapshot(), {"ingest_kb_document"})}
    assert keys["failed_task:ingest_kb_document"] is False


def check(active: bool = True, grace: timedelta = timedelta(0)) -> Check:
    return Check("k", active, "Очередь", "много", grace)


@pytest.mark.parametrize(
    ("chk", "state", "expected"),
    [
        (check(), None, Decision.FIRE),
        (check(active=False), None, Decision.NONE),
        (check(active=False), AlertState(NOW - MIN, None), Decision.NONE),
        (check(active=False), AlertState(NOW - MIN, NOW - MIN), Decision.RESOLVE),
        (check(), AlertState(NOW - MIN, NOW - MIN), Decision.NONE),
        (check(), AlertState(NOW - 7 * 60 * MIN, NOW - 6 * 60 * MIN), Decision.REPEAT),
        # LiteLLM: ждём 2 минуты подряд недоступности.
        (check(grace=2 * MIN), None, Decision.NONE),
        (check(grace=2 * MIN), AlertState(NOW - MIN, None), Decision.NONE),
        (check(grace=2 * MIN), AlertState(NOW - 2 * MIN, None), Decision.FIRE),
    ],
)
def test_decide(chk: Check, state: AlertState | None, expected: Decision) -> None:
    assert decide(chk, state, NOW) is expected


def test_message() -> None:
    assert message(check(), Decision.FIRE) == "⚠️ Очередь: много"
    assert message(check(), Decision.REPEAT) == "⚠️ Очередь: много (всё ещё)"
    assert message(check(), Decision.RESOLVE) == "✅ Очередь: в норме"


@pytest.mark.parametrize(
    ("spent", "daily", "expected"),
    [
        (0.0, 10.0, BudgetState.OK),
        (8.0, 10.0, BudgetState.OK),
        (8.5, 10.0, BudgetState.WARN),
        (10.0, 10.0, BudgetState.OVER),
        (99.0, 0.0, BudgetState.OK),
    ],
)
def test_budget_state(spent: float, daily: float, expected: BudgetState) -> None:
    assert budget_state(spent, daily) is expected


@pytest.mark.parametrize(
    ("state", "enabled", "expected"),
    [
        (BudgetState.OVER, True, True),
        (BudgetState.OVER, False, False),
        (BudgetState.WARN, True, False),
    ],
)
def test_use_fallback(state: BudgetState, enabled: bool, expected: bool) -> None:
    assert use_fallback(state, enabled) is expected


@pytest.mark.parametrize(
    ("now", "expected_utc"),
    [
        (datetime(2026, 10, 8, 10, 0, tzinfo=UTC), datetime(2026, 10, 7, 19, 0, tzinfo=UTC)),
        (datetime(2026, 10, 8, 19, 30, tzinfo=UTC), datetime(2026, 10, 8, 19, 0, tzinfo=UTC)),
    ],
)
def test_day_start_tashkent(now: datetime, expected_utc: datetime) -> None:
    assert day_start(now, "Asia/Tashkent") == expected_utc


def test_model_checks_only_when_probed() -> None:
    """Не проверяли модели в эту минуту — проверок по ним нет (ни алерта, ни «в норме»)."""
    assert not [c for c in checks(HealthSnapshot()) if c.key.startswith("model:")]
    probed = checks(HealthSnapshot(models={"dialog-model": None}))
    assert [(c.key, c.active) for c in probed if c.key.startswith("model:")] == [
        ("model:dialog-model", False)
    ]


@pytest.mark.parametrize(
    ("status", "text", "kind"),
    [
        (400, "Your credit balance is too low to access the Anthropic API.", "кредиты"),
        (
            429,
            "You exceeded your current quota, please check your plan and billing details.",
            "кредиты",
        ),
        (401, "invalid x-api-key", "ключ"),
        (403, "Permission denied", "ключ"),
        (529, "Overloaded", None),
        (429, "Rate limit: too many requests per minute", None),
        (None, "timeout", None),
    ],
)
def test_provider_problem(status: int | None, text: str, kind: str | None) -> None:
    problem = provider_problem(status, text)
    if kind is None:
        assert problem is None
    else:
        assert problem is not None
        assert kind in problem


def test_model_probe_due_hourly() -> None:
    assert model_probe_due(NOW)  # 10:00
    assert not model_probe_due(NOW + 15 * MIN)
    assert model_probe_due(NOW + 60 * MIN)
