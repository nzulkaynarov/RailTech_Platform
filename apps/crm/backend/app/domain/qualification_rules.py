"""Когда лид «Квалифицирован» (BUSINESS §5, ADR-0016): решает код по настраиваемым критериям.

Модель только извлекает факты (потребность, продукт, срок, роль, бюджет, компания);
стадию `qualified` выставляет этот модуль. Критерии задаёт админ в «Настройки →
Квалификация», по умолчанию — BUSINESS §5: потребность и продукт, а также хотя бы
одно из: срок, роль в решении, бюджет.
"""

from dataclasses import dataclass, field
from typing import Final, Literal

from app.domain.qualification import DecisionRole, Timeline
from app.domain.stages import Stage

Fact = Literal["need", "product", "timeline", "decision_role", "budget", "company"]
TIMELINE_ORDER: Final[tuple[Timeline, ...]] = ("<1m", "<3m", "<12m", ">12m")
ALL_ROLES: Final[frozenset[DecisionRole]] = frozenset(
    {"decision_maker", "influencer", "researcher"}
)


@dataclass(frozen=True, slots=True)
class QualificationCriteria:
    required: frozenset[Fact] = frozenset({"need", "product"})
    any_of: frozenset[Fact] = frozenset({"timeline", "decision_role", "budget"})
    min_any_of: int = 1
    # Срок засчитывается, если он не дальше этого горизонта (">12m" — любой известный).
    timeline_max: Timeline = ">12m"
    # Какие роли в решении засчитываются (например, только ЛПР).
    decision_roles: frozenset[DecisionRole] = field(default_factory=lambda: ALL_ROLES)


@dataclass(frozen=True, slots=True)
class LeadFacts:
    need: bool
    product: bool
    timeline: Timeline | None
    decision_role: DecisionRole | None
    budget: bool
    company: bool


def known_facts(facts: LeadFacts, criteria: QualificationCriteria) -> frozenset[Fact]:
    """Факты, которые засчитываются по критериям (срок — в пределах горизонта и т. п.)."""
    horizon = TIMELINE_ORDER.index(criteria.timeline_max)
    known: set[Fact] = set()
    if facts.need:
        known.add("need")
    if facts.product:
        known.add("product")
    if facts.timeline is not None and TIMELINE_ORDER.index(facts.timeline) <= horizon:
        known.add("timeline")
    if facts.decision_role in criteria.decision_roles:
        known.add("decision_role")
    if facts.budget:
        known.add("budget")
    if facts.company:
        known.add("company")
    return frozenset(known)


def is_qualified(facts: LeadFacts, criteria: QualificationCriteria) -> bool:
    known = known_facts(facts, criteria)
    enough = len(criteria.any_of & known) >= criteria.min_any_of
    return criteria.required <= known and enough


def stage_for(proposed: Stage, qualified: bool) -> Stage:
    """Стадия по правилам: `qualified` — только по критериям; иначе предложение модели."""
    if qualified:
        return Stage.QUALIFIED
    return Stage.ENGAGED if proposed == Stage.QUALIFIED else proposed
