import pytest

from app.domain.stage_machine import decide, stage_before_handoff
from app.domain.stages import Stage as S
from app.domain.stages import TransitionSource as Src

ALLOWED = [
    (S.NEW, S.ENGAGED, Src.QUALIFIER),
    (S.ENGAGED, S.QUALIFIED, Src.QUALIFIER),
    (S.NEW, S.HANDOFF, Src.TRIGGER),
    (S.ENGAGED, S.HANDOFF, Src.TRIGGER),
    (S.QUALIFIED, S.HANDOFF, Src.TRIGGER),
    (S.UNRESPONSIVE, S.HANDOFF, Src.TRIGGER),
    (S.HANDOFF, S.IN_PROGRESS, Src.USER),
    (S.NEW, S.IN_PROGRESS, Src.USER),
    (S.ENGAGED, S.IN_PROGRESS, Src.USER),
    (S.QUALIFIED, S.IN_PROGRESS, Src.USER),
    (S.UNRESPONSIVE, S.IN_PROGRESS, Src.USER),
    (S.HANDOFF, S.ENGAGED, Src.USER),
    (S.HANDOFF, S.QUALIFIED, Src.USER),
    (S.IN_PROGRESS, S.WON, Src.USER),
    (S.IN_PROGRESS, S.LOST, Src.USER),
    (S.IN_PROGRESS, S.ENGAGED, Src.USER),
    (S.IN_PROGRESS, S.QUALIFIED, Src.USER),
    (S.WON, S.CUSTOMER, Src.USER),
    (S.WON, S.CUSTOMER, Src.SYSTEM),
    (S.NEW, S.UNRESPONSIVE, Src.TIMER),
    (S.ENGAGED, S.UNRESPONSIVE, Src.TIMER),
    (S.QUALIFIED, S.UNRESPONSIVE, Src.TIMER),
    (S.HANDOFF, S.UNRESPONSIVE, Src.TIMER),
    (S.UNRESPONSIVE, S.ENGAGED, Src.SYSTEM),
]

REJECTED = [
    (S.NEW, S.QUALIFIED, Src.QUALIFIER),
    (S.QUALIFIED, S.ENGAGED, Src.QUALIFIER),
    (S.ENGAGED, S.HANDOFF, Src.QUALIFIER),
    (S.NEW, S.WON, Src.QUALIFIER),
    (S.NEW, S.ENGAGED, Src.USER),
    (S.ENGAGED, S.HANDOFF, Src.USER),
    (S.IN_PROGRESS, S.HANDOFF, Src.TRIGGER),
    (S.WON, S.HANDOFF, Src.TRIGGER),
    (S.CUSTOMER, S.HANDOFF, Src.TRIGGER),
    (S.LOST, S.HANDOFF, Src.TRIGGER),
    (S.HANDOFF, S.WON, Src.USER),
    (S.IN_PROGRESS, S.UNRESPONSIVE, Src.TIMER),
    (S.WON, S.UNRESPONSIVE, Src.TIMER),
    (S.CUSTOMER, S.UNRESPONSIVE, Src.TIMER),
    (S.LOST, S.UNRESPONSIVE, Src.TIMER),
    (S.UNRESPONSIVE, S.ENGAGED, Src.QUALIFIER),
    (S.UNRESPONSIVE, S.QUALIFIED, Src.SYSTEM),
    (S.WON, S.CUSTOMER, Src.TIMER),
    (S.LOST, S.ENGAGED, Src.USER),
    (S.ENGAGED, S.IN_PROGRESS, Src.TRIGGER),
    (S.WON, S.IN_PROGRESS, Src.USER),
    (S.LOST, S.IN_PROGRESS, Src.USER),
    (S.CUSTOMER, S.ENGAGED, Src.SYSTEM),
]


@pytest.mark.parametrize(("current", "target", "source"), ALLOWED)
def test_allowed(current: S, target: S, source: Src) -> None:
    decision = decide(current, target, source)
    assert decision.allowed
    assert decision.changed
    assert decision.reason is None


@pytest.mark.parametrize(("current", "target", "source"), REJECTED)
def test_rejected_with_reason(current: S, target: S, source: Src) -> None:
    decision = decide(current, target, source)
    assert not decision.allowed
    assert not decision.changed
    assert decision.reason


@pytest.mark.parametrize("stage", list(S))
def test_same_stage_is_noop(stage: S) -> None:
    decision = decide(stage, stage, Src.QUALIFIER)
    assert decision.allowed
    assert not decision.changed


@pytest.mark.parametrize(
    ("history", "expected"),
    [
        ([], S.ENGAGED),
        ([(S.NEW, S.ENGAGED), (S.ENGAGED, S.QUALIFIED), (S.QUALIFIED, S.HANDOFF)], S.QUALIFIED),
        ([(S.NEW, S.HANDOFF)], S.ENGAGED),
        ([(S.QUALIFIED, S.HANDOFF), (S.HANDOFF, S.ENGAGED), (S.ENGAGED, S.HANDOFF)], S.ENGAGED),
        ([(S.ENGAGED, S.QUALIFIED), (S.QUALIFIED, S.IN_PROGRESS)], S.QUALIFIED),
        ([(S.QUALIFIED, S.HANDOFF), (S.HANDOFF, S.IN_PROGRESS)], S.QUALIFIED),
    ],
)
def test_stage_before_handoff(history: list[tuple[S, S]], expected: S) -> None:
    assert stage_before_handoff(history) == expected
