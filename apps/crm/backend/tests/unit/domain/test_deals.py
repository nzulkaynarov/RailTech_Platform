"""Переходы стадий сделки и итог при закрытии лида (ADR-0019)."""

import pytest

from app.domain.deals import (
    OTHER_REASON,
    DealStage,
    ErpOutcome,
    OutcomePlan,
    deal_title,
    lost_reason,
    may_edit,
    may_transition,
    plan_erp_outcome,
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
        # Q-021: отказ без открытой сделки — проигранная сделка с причиной.
        ("lost", False, "Дорого", OutcomePlan(create=True, stage=L, lost_reason="Дорого")),
        ("lost", False, None, OutcomePlan(create=True, stage=L, lost_reason=OTHER_REASON)),
    ],
)
def test_plan_lead_outcome(
    outcome: str, has_open: bool, code: str | None, expected: OutcomePlan | None
) -> None:
    assert plan_lead_outcome(outcome, has_open, code, REASONS) == expected


@pytest.mark.parametrize(
    ("stage", "is_admin", "allowed"),
    [(OP, False, True), (L, False, True), (W, False, False), (W, True, True), (OP, True, True)],
)
def test_may_edit(stage: DealStage, is_admin: bool, allowed: bool) -> None:
    assert may_edit(stage, is_admin=is_admin) is allowed


@pytest.mark.parametrize(
    ("client", "lead", "product", "expected"),
    [
        ("ООО Тест", "Иван", "Вагоны", "ООО Тест — Вагоны"),
        (None, "Иван", "Вагоны", "Иван — Вагоны"),
        ("  ", "Иван", None, "Иван"),
        (None, None, "Вагоны", "Лид #7 — Вагоны"),
        (None, "", "", "Лид #7"),
        ("A" * 300, None, "X", "A" * 255),
    ],
)
def test_deal_title(
    client: str | None, lead: str | None, product: str | None, expected: str
) -> None:
    got = deal_title(client_name=client, lead_name=lead, product_name=product, lead_id=7)
    assert got == expected


@pytest.mark.parametrize(
    ("event", "current", "reason", "expected"),
    [
        ("deal.won", OP, None, ErpOutcome(stage=W, changed=True, lost_reason=None)),
        ("deal.won", W, None, ErpOutcome(stage=W, changed=False, lost_reason=None)),  # повтор
        ("deal.won", L, None, ErpOutcome(stage=W, changed=True, lost_reason=None)),
        ("deal.lost", OP, "Дорого", ErpOutcome(stage=L, changed=True, lost_reason="Дорого")),
        # Причина — текстом ERP, не из справочника CRM; пусто — «Другое».
        ("deal.lost", OP, "Ушли к конкуренту", ErpOutcome(L, True, "Ушли к конкуренту")),
        ("deal.lost", OP, "  ", ErpOutcome(stage=L, changed=True, lost_reason=OTHER_REASON)),
        ("deal.lost", L, "Дорого", ErpOutcome(stage=L, changed=False, lost_reason="Дорого")),
        # ERP — источник истины зеркала: «выиграна» не финал для события ERP (ADR-0022).
        ("deal.lost", W, None, ErpOutcome(stage=L, changed=True, lost_reason=OTHER_REASON)),
    ],
)
def test_plan_erp_outcome(
    event: str, current: DealStage, reason: str | None, expected: ErpOutcome
) -> None:
    assert plan_erp_outcome(event, current, reason) == expected


@pytest.mark.parametrize("event", ["deal.stage_changed", "quote.sent", "won", ""])
def test_plan_erp_outcome_rejects_other_events(event: str) -> None:
    with pytest.raises(ValueError, match="not a deal outcome event"):
        plan_erp_outcome(event, OP, None)
