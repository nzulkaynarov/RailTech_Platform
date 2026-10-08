import pytest

from app.domain.triggers import (
    Priority,
    TriggerCode,
    TriggerSettings,
    TriggerSignals,
    evaluate,
)

T = TriggerCode
CFG = TriggerSettings()


@pytest.mark.parametrize(
    ("signals", "expected"),
    [
        (TriggerSignals(), []),
        (TriggerSignals(human_requested=True), [T.HUMAN_REQUESTED]),
        (TriggerSignals(callback_requested=True), [T.CALLBACK_REQUESTED]),
        (TriggerSignals(intent="request_contact"), [T.CALLBACK_REQUESTED]),
        (TriggerSignals(intent="pricing", kb_best_score=0.3), [T.PRICE_OR_CONTRACT_ASKED]),
        (TriggerSignals(intent="pricing", kb_best_score=None), [T.PRICE_OR_CONTRACT_ASKED]),
        (TriggerSignals(intent="pricing", kb_best_score=0.8), []),
        (TriggerSignals(sentiment="negative"), [T.NEGATIVE_SENTIMENT]),
        (TriggerSignals(stop_word_hit=True), [T.NEGATIVE_SENTIMENT]),
        (TriggerSignals(intent="complaint"), [T.COMPLAINT]),
        (TriggerSignals(consecutive_fallbacks=1), []),
        (TriggerSignals(consecutive_fallbacks=2), [T.KB_GAP_STREAK]),
        (TriggerSignals(bot_turns_without_progress=3), []),
        (TriggerSignals(bot_turns_without_progress=4), [T.NO_PROGRESS]),
        (TriggerSignals(competitor_mentioned=True), [T.COMPETITOR_MENTIONED]),
        (TriggerSignals(score=69), []),
        (TriggerSignals(score=70), [T.HIGH_SCORE]),
        (TriggerSignals(recommend_escalation=True, confidence=0.69), []),
        (TriggerSignals(recommend_escalation=True, confidence=0.7), [T.QUALIFIER_RECOMMEND]),
        (TriggerSignals(document_not_found=True), []),
        (TriggerSignals(document_not_found=True, customer_mode=True), [T.DOCUMENT_NOT_FOUND]),
        (TriggerSignals(intent="service"), []),
        (TriggerSignals(intent="service", customer_mode=True), [T.SERVICE_REQUEST]),
        (TriggerSignals(attachment_received=True), [T.ATTACHMENT_RECEIVED]),
    ],
)
def test_each_trigger(signals: TriggerSignals, expected: list[TriggerCode]) -> None:
    assert [h.code for h in evaluate(signals, CFG)] == expected


def test_hits_sorted_by_priority() -> None:
    signals = TriggerSignals(score=90, human_requested=True, attachment_received=True)
    assert [h.priority for h in evaluate(signals, CFG)] == [
        Priority.HOT,
        Priority.WARM,
        Priority.INFO,
    ]


def test_disabled_trigger_is_skipped() -> None:
    cfg = TriggerSettings(disabled=frozenset({T.HIGH_SCORE}))
    assert evaluate(TriggerSignals(score=95), cfg) == []


def test_thresholds_are_configurable() -> None:
    cfg = TriggerSettings(high_score_threshold=50, no_progress_turns=2, kb_gap_streak=3)
    codes = {
        h.code
        for h in evaluate(
            TriggerSignals(score=55, bot_turns_without_progress=2, consecutive_fallbacks=2), cfg
        )
    }
    assert codes == {T.HIGH_SCORE, T.NO_PROGRESS}
