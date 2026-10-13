import pytest

from app.domain.qualification_rules import (
    LeadFacts,
    QualificationCriteria,
    is_qualified,
    stage_for,
)
from app.domain.stages import Stage

DEFAULT = QualificationCriteria()  # BUSINESS §5


def facts(**known: object) -> LeadFacts:
    base: dict[str, object] = {
        "need": False,
        "product": False,
        "timeline": None,
        "decision_role": None,
        "budget": False,
        "company": False,
    }
    return LeadFacts(**{**base, **known})  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("lead", "criteria", "expected"),
    [
        # BUSINESS §5: потребность и продукт + хотя бы одно из срока, роли, бюджета.
        (facts(need=True, product=True), DEFAULT, False),  # «хочу купить кассу» — ещё нет
        (facts(need=True, product=True, timeline=">12m"), DEFAULT, True),
        (facts(need=True, product=True, decision_role="researcher"), DEFAULT, True),
        (facts(need=True, product=True, budget=True), DEFAULT, True),
        (facts(need=True, timeline="<3m", decision_role="decision_maker"), DEFAULT, False),
        (facts(product=True, timeline="<3m"), DEFAULT, False),
        # Другой бизнес: нужны продукт и ЛПР, срок ≤ 3 мес.
        (
            facts(need=True, product=True, timeline="<12m", decision_role="decision_maker"),
            QualificationCriteria(
                required=frozenset({"need", "product"}),
                any_of=frozenset({"timeline", "decision_role"}),
                min_any_of=2,
                timeline_max="<3m",
                decision_roles=frozenset({"decision_maker"}),
            ),
            False,
        ),
        (
            facts(need=True, product=True, timeline="<1m", decision_role="decision_maker"),
            QualificationCriteria(
                required=frozenset({"need", "product"}),
                any_of=frozenset({"timeline", "decision_role"}),
                min_any_of=2,
                timeline_max="<3m",
                decision_roles=frozenset({"decision_maker"}),
            ),
            True,
        ),
        # Бюджет как обязательный факт.
        (
            facts(need=True, product=True),
            QualificationCriteria(required=frozenset({"budget"})),
            False,
        ),
    ],
)
def test_is_qualified(lead: LeadFacts, criteria: QualificationCriteria, expected: bool) -> None:
    assert is_qualified(lead, criteria) is expected


@pytest.mark.parametrize(
    ("proposed", "qualified", "expected"),
    [
        (Stage.ENGAGED, True, Stage.QUALIFIED),
        (Stage.NEW, True, Stage.QUALIFIED),
        (Stage.QUALIFIED, False, Stage.ENGAGED),  # модель не может «квалифицировать» сама
        (Stage.ENGAGED, False, Stage.ENGAGED),
        (Stage.NEW, False, Stage.NEW),
    ],
)
def test_stage_for(proposed: Stage, qualified: bool, expected: Stage) -> None:
    assert stage_for(proposed, qualified) is expected
