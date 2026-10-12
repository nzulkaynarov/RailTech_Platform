"""Переходы стадий сделки и итог при закрытии лида (ADR-0019)."""

import pytest

from app.domain.deals import (
    OTHER_REASON,
    DealStage,
    OutcomePlan,
    lost_reason,
    may_transition,
    plan_lead_outcome,
)

OP, W, L = DealStage.OPEN, DealStage.WON, DealStage.LOST
REASONS = ["Дорого", "Нет бюджета", OTHER_REASON]


@pytest.mark.parametrize(
    ("current", "target", "is_admin", "allowed"),
    [
        (OP, W, False, True),
        (OP, L, False, True),
        (OP, OP, False, True),
        (L, OP, False, True),
        (L, W, False, True),
        (W, W, False, True),
        (W, OP, False, False),
        (W, L, False, False),
        (W, OP, True, True),
        (W, L, True, True),
    ],
)
def test_may_transition(
    current: DealStage, target: DealStage, is_admin: bool, allowed: bool
) -> None:
    assert may_transition(current, target, is_admin=is_admin) is allowed


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("Дорого", "Дорого"),
        (" Нет бюджета ", "Нет бюджета"),
        ("не знаю", OTHER_REASON),
        (None, OTHER_REASON),
        ("", OTHER_REASON),
    ],
)
def test_lost_reason(code: str | None, expected: str) -> None:
    assert lost_reason(code, REASONS) == expected


@pytest.mark.parametrize(
    ("outcome", "has_open", "code", "expected"),
    [
        ("won", True, None, OutcomePlan(create=False, stage=W, lost_reason=None)),
        ("won", False, None, OutcomePlan(create=True, stage=W, lost_reason=None)),
        ("lost", True, "Дорого", OutcomePlan(create=False, stage=L, lost_reason="Дорого")),
        ("lost", True, "Клиент передумал", OutcomePlan(False, L, OTHER_REASON)),
        ("lost", False, "Дорого", None),
    ],
)
def test_plan_lead_outcome(
    outcome: str, has_open: bool, code: str | None, expected: OutcomePlan | None
) -> None:
    assert plan_lead_outcome(outcome, has_open, code, REASONS) == expected
