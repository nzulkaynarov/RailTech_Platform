from datetime import UTC, datetime

import pytest

from app.domain.consent import consent_required
from app.domain.keywords import find_terms
from app.domain.qualification import (
    LeadSignals,
    Qualification,
    QualifierOutput,
    merge_qualification,
    update_signals,
)

NOW = datetime(2026, 10, 8, tzinfo=UTC)


@pytest.mark.parametrize(
    ("given_at", "version", "current", "expected"),
    [
        (None, None, "v1", True),
        (NOW, "v1", "v1", False),
        (NOW, "v1", "v2", True),
        (NOW, None, "v1", True),
    ],
)
def test_consent_required(
    given_at: datetime | None, version: str | None, current: str, expected: bool
) -> None:
    assert consent_required(given_at, version, current) is expected


@pytest.mark.parametrize(
    ("text", "terms", "expected"),
    [
        ("Позовите менеджера, пожалуйста", ["менеджера", "оператор"], ["менеджера"]),
        ("А у Конкурент-Софт дешевле", ["конкурент софт"], ["конкурент софт"]),
        ("операторы связи", ["оператор"], []),
        ("Operator kerak", ["operator"], ["operator"]),
        ("", ["x"], []),
    ],
)
def test_find_terms(text: str, terms: list[str], expected: list[str]) -> None:
    assert find_terms(text, terms) == expected


def test_merge_qualification_keeps_known_values() -> None:
    current = Qualification(timeline="<3m", company="ООО Ромашка")
    merged = merge_qualification(
        current, Qualification(timeline=None, decision_role="influencer", company="")
    )
    assert merged == Qualification(
        timeline="<3m", company="ООО Ромашка", decision_role="influencer"
    )


@pytest.mark.parametrize(
    ("intent", "callback", "expected"),
    [
        ("pricing", False, LeadSignals(asked_price=True)),
        ("request_contact", False, LeadSignals(requested_contact=True)),
        ("info", True, LeadSignals(requested_contact=True)),
        ("info", False, LeadSignals()),
    ],
)
def test_update_signals(intent: str, callback: bool, expected: LeadSignals) -> None:
    output = QualifierOutput(
        intent=intent, sentiment="neutral", proposed_stage="engaged", confidence=0.5
    )
    assert update_signals(LeadSignals(), output, callback) == expected


def test_signals_are_sticky() -> None:
    output = QualifierOutput(
        intent="info", sentiment="neutral", proposed_stage="engaged", confidence=0.5
    )
    assert update_signals(LeadSignals(asked_price=True), output, False).asked_price


def test_qualifier_output_rejects_unknown_stage() -> None:
    with pytest.raises(ValueError, match="proposed_stage"):
        QualifierOutput(intent="info", sentiment="neutral", proposed_stage="won", confidence=0.5)
