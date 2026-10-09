"""Score лида 0..100 — детерминированная функция (SPEC §6.3).

Веса — в коде с тестами, не в настройках: изменение веса — осознанное решение
с ADR-заметкой.
"""

from dataclasses import dataclass
from typing import Final

from app.domain.qualification import DecisionRole, Timeline

NEED: Final = 25
PRODUCT: Final = 15
TIMELINE: Final[dict[Timeline, int]] = {"<1m": 20, "<3m": 20, "<12m": 10, ">12m": 0}
ROLE: Final[dict[DecisionRole, int]] = {"decision_maker": 20, "influencer": 10, "researcher": 0}
ASKED_PRICE: Final = 15
REQUESTED_CONTACT: Final = 25
NEGATIVE: Final = -10


@dataclass(frozen=True, slots=True)
class ScoreInputs:
    has_need: bool
    has_product: bool
    timeline: Timeline | None
    decision_role: DecisionRole | None
    asked_price: bool
    requested_contact: bool
    negative: bool


def compute_score(inputs: ScoreInputs) -> int:
    score = 0
    score += NEED if inputs.has_need else 0
    score += PRODUCT if inputs.has_product else 0
    score += TIMELINE[inputs.timeline] if inputs.timeline else 0
    score += ROLE[inputs.decision_role] if inputs.decision_role else 0
    score += ASKED_PRICE if inputs.asked_price else 0
    score += REQUESTED_CONTACT if inputs.requested_contact else 0
    score += NEGATIVE if inputs.negative else 0
    return max(0, min(100, score))
