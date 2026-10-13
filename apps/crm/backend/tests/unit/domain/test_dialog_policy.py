import pytest

from app.domain.dialog_policy import Action, DecisionInput, decide, is_smalltalk
from app.domain.stages import OwnerMode, Stage


def make(**overrides: object) -> DecisionInput:
    base: dict[str, object] = {
        "owner_mode": OwnerMode.BOT,
        "stage": Stage.ENGAGED,
        "text": "Сколько стоит касса?",
        "human_requested": False,
        "stop_word_hit": False,
        "best_score": 0.8,
        "min_score": 0.55,
        "need_known": True,
    }
    base.update(overrides)
    return DecisionInput(**base)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("overrides", "action", "clarify"),
    [
        ({}, Action.ANSWER, False),
        ({"owner_mode": OwnerMode.HUMAN}, Action.SILENT, False),
        ({"owner_mode": OwnerMode.PAUSED, "human_requested": True}, Action.SILENT, False),
        ({"human_requested": True}, Action.HANDOFF, False),
        ({"stop_word_hit": True}, Action.HANDOFF, False),
        ({"document_match": True}, Action.DELIVER_DOCUMENT, False),
        ({"best_score": 0.3}, Action.FALLBACK, False),
        ({"best_score": None}, Action.FALLBACK, False),
        ({"best_score": 0.3, "text": "Спасибо!"}, Action.ANSWER, False),
        ({"best_score": None, "text": "Salom"}, Action.ANSWER, False),
        ({"need_known": False}, Action.ANSWER, True),
        ({"need_known": False, "stage": Stage.QUALIFIED}, Action.ANSWER, False),
        ({"need_known": False, "text": "привет"}, Action.ANSWER, False),
        ({"best_score": 0.55}, Action.ANSWER, False),
    ],
)
def test_decide(overrides: dict[str, object], action: Action, clarify: bool) -> None:
    decision = decide(make(**overrides))
    assert decision.action == action
    assert decision.clarify is clarify
    assert decision.reason


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Привет", True),
        ("Спасибо!", True),
        ("rahmat", True),
        ("OK", True),
        ("Хорошо, понял", True),
        ("Сколько стоит касса?", False),
        ("narxi qancha", False),
        ("What do you sell", False),
        ("Интеграция с 1С для трёх магазинов", False),
    ],
)
def test_is_smalltalk(text: str, expected: bool) -> None:
    assert is_smalltalk(text) is expected


@pytest.mark.parametrize(
    ("match", "requested", "found", "expected", "reason"),
    [
        (True, True, 1, Action.DELIVER_DOCUMENT, "document_match"),
        (False, True, 0, Action.HANDOFF, "document_not_found"),
        (False, True, 3, Action.CHOOSE_DOCUMENT, "documents_ambiguous"),
        (False, False, 0, Action.ANSWER, "kb"),
    ],
)
def test_customer_documents(
    match: bool, requested: bool, found: int, expected: Action, reason: str
) -> None:
    decision = decide(
        DecisionInput(
            owner_mode=OwnerMode.BOT,
            stage=Stage.CUSTOMER,
            text="Пришлите договор за июль",
            human_requested=False,
            stop_word_hit=False,
            best_score=0.9,
            min_score=0.55,
            need_known=True,
            document_match=match,
            document_requested=requested,
            documents_found=found,
        )
    )
    assert (decision.action, decision.reason) == (expected, reason)


def test_customer_without_kb_answer_is_not_a_kb_gap() -> None:
    decision = decide(
        DecisionInput(
            owner_mode=OwnerMode.BOT,
            stage=Stage.CUSTOMER,
            text="Касса не печатает чеки, помогите",
            human_requested=False,
            stop_word_hit=False,
            best_score=0.2,
            min_score=0.55,
            need_known=True,
            customer=True,
        )
    )
    assert (decision.action, decision.reason) == (Action.ANSWER, "customer_service")
