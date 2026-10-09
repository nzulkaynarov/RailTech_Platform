"""Постобработка квалификатора: стадии, score, прогресс, триггеры (таблицы кейсов)."""

from dataclasses import replace
from typing import Any

import pytest

from app.domain.qualification import LeadSignals, Qualification, QualifierOutput
from app.domain.qualifier_decision import LeadState, TurnFacts, decide
from app.domain.stage_machine import qualifier_path
from app.domain.stages import Stage
from app.domain.triggers import TriggerCode, TriggerSettings

S = Stage
CFG = TriggerSettings()
BASE = LeadState(
    stage=S.ENGAGED,
    score=25,
    qualification=Qualification(),
    signals=LeadSignals(),
    need_summary="касса для магазина",
    product_interest=(),
    bot_turns_without_progress=0,
)
FACTS = TurnFacts(
    kb_best_score=0.8, min_score=0.55, competitor_mentioned=False, known_products={"pos", "track"}
)


def output(**overrides: Any) -> QualifierOutput:
    base: dict[str, Any] = {
        "intent": "info",
        "sentiment": "neutral",
        "proposed_stage": "engaged",
        "confidence": 0.8,
    }
    return QualifierOutput.model_validate({**base, **overrides})


def codes(state: LeadState, out: QualifierOutput, facts: TurnFacts = FACTS) -> set[TriggerCode]:
    return {h.code for h in decide(state, out, facts, CFG).hits}


@pytest.mark.parametrize(
    ("current", "proposed", "path", "rejected"),
    [
        (S.NEW, S.ENGAGED, (S.ENGAGED,), False),
        (S.NEW, S.QUALIFIED, (S.ENGAGED, S.QUALIFIED), False),
        (S.ENGAGED, S.QUALIFIED, (S.QUALIFIED,), False),
        (S.ENGAGED, S.ENGAGED, (), False),
        (S.QUALIFIED, S.ENGAGED, (), True),
        (S.ENGAGED, S.NEW, (), True),
        (S.HANDOFF, S.QUALIFIED, (), True),
        (S.IN_PROGRESS, S.ENGAGED, (), True),
        (S.UNRESPONSIVE, S.ENGAGED, (), True),
    ],
)
def test_qualifier_path(
    current: Stage, proposed: Stage, path: tuple[Stage, ...], rejected: bool
) -> None:
    got_path, reason = qualifier_path(current, proposed)
    assert got_path == path
    assert (reason is not None) is rejected


def test_rejected_proposal_is_recorded_and_stage_kept() -> None:
    decision = decide(
        replace(BASE, stage=S.QUALIFIED), output(proposed_stage="engaged"), FACTS, CFG
    )
    assert decision.stage_path == ()
    assert decision.final_stage is None
    assert decision.rejected_reason


@pytest.mark.parametrize(
    ("overrides", "expected_score"),
    [
        ({}, 25),
        ({"product_interest": ["pos"]}, 40),
        ({"product_interest": ["unknown-product"]}, 25),
        ({"intent": "pricing"}, 40),
        ({"intent": "request_contact"}, 50),
        ({"sentiment": "negative"}, 15),
        ({"qualification": {"timeline": "<3m", "decision_role": "decision_maker"}}, 65),
        ({"qualification": {"timeline": "<12m", "decision_role": "influencer"}}, 45),
    ],
)
def test_score(overrides: dict[str, Any], expected_score: int) -> None:
    assert decide(BASE, output(**overrides), FACTS, CFG).score == expected_score


def test_qualification_merge_keeps_known_values() -> None:
    state = replace(BASE, qualification=Qualification(company="Ромашка", timeline="<3m"))
    decision = decide(state, output(qualification={"region": "Ташкент"}), FACTS, CFG)
    assert decision.qualification == Qualification(
        company="Ромашка", timeline="<3m", region="Ташкент"
    )


def test_sticky_signals_survive_next_run() -> None:
    first = decide(BASE, output(intent="pricing"), FACTS, CFG)
    second = decide(replace(BASE, signals=first.signals), output(intent="info"), FACTS, CFG)
    assert second.signals.asked_price
    assert second.score == first.score


@pytest.mark.parametrize(
    ("state_turns", "score_before", "out", "expected_turns"),
    [
        (2, 25, output(), 3),
        (2, 25, output(proposed_stage="qualified"), 0),
        (2, 25, output(product_interest=["pos"]), 0),
        (0, 25, output(), 1),
    ],
)
def test_no_progress_counter(
    state_turns: int, score_before: int, out: QualifierOutput, expected_turns: int
) -> None:
    state = replace(BASE, bot_turns_without_progress=state_turns, score=score_before)
    assert decide(state, out, FACTS, CFG).bot_turns_without_progress == expected_turns


@pytest.mark.parametrize(
    ("state", "out", "facts", "expected"),
    [
        (BASE, output(), FACTS, set()),
        (BASE, output(intent="request_contact"), FACTS, {TriggerCode.CALLBACK_REQUESTED}),
        (
            BASE,
            output(intent="pricing"),
            replace(FACTS, kb_best_score=0.3),
            {TriggerCode.PRICE_OR_CONTRACT_ASKED},
        ),
        (BASE, output(intent="pricing"), FACTS, set()),
        (BASE, output(sentiment="negative"), FACTS, {TriggerCode.NEGATIVE_SENTIMENT}),
        (BASE, output(intent="complaint"), FACTS, {TriggerCode.COMPLAINT}),
        (
            BASE,
            output(),
            replace(FACTS, competitor_mentioned=True),
            {TriggerCode.COMPETITOR_MENTIONED},
        ),
        (
            BASE,
            output(recommend_escalation=True, confidence=0.9),
            FACTS,
            {TriggerCode.QUALIFIER_RECOMMEND},
        ),
        (BASE, output(recommend_escalation=True, confidence=0.5), FACTS, set()),
        (replace(BASE, bot_turns_without_progress=3), output(), FACTS, {TriggerCode.NO_PROGRESS}),
        (replace(BASE, bot_turns_without_progress=4), output(), FACTS, set()),
    ],
    ids=[
        "none",
        "contact",
        "price-no-kb",
        "price-in-kb",
        "negative",
        "complaint",
        "competitor",
        "recommend",
        "recommend-low-confidence",
        "no-progress-edge",
        "no-progress-after-edge",
    ],
)
def test_triggers(
    state: LeadState, out: QualifierOutput, facts: TurnFacts, expected: set[TriggerCode]
) -> None:
    assert codes(state, out, facts) == expected


def test_high_score_fires_only_on_crossing() -> None:
    hot = output(
        product_interest=["pos"],
        intent="request_contact",
        qualification={"timeline": "<1m", "decision_role": "decision_maker"},
    )
    assert TriggerCode.HIGH_SCORE in codes(BASE, hot)
    assert TriggerCode.HIGH_SCORE not in codes(replace(BASE, score=80), hot)
