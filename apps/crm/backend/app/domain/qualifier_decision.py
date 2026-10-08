"""Постобработка вывода квалификатора (SPEC §7.2): модель предлагает, код решает.

Порядок: квалификация и сигналы → путь стадий через state machine → score →
счётчик «нет прогресса» → триггеры. Триггеры по состоянию (score, «нет
прогресса») срабатывают на пересечении порога, а не на каждом прогоне, —
иначе после возврата лида боту эскалация повторялась бы сразу.
"""

from collections.abc import Collection
from dataclasses import dataclass
from typing import Final

from app.domain.qualification import (
    LeadSignals,
    Qualification,
    QualifierOutput,
    merge_qualification,
    update_signals,
)
from app.domain.scoring import ScoreInputs, compute_score
from app.domain.stage_machine import qualifier_path
from app.domain.stages import Stage
from app.domain.triggers import TriggerHit, TriggerSettings, TriggerSignals, evaluate

MAX_PRODUCTS: Final = 10


@dataclass(frozen=True, slots=True)
class LeadState:
    stage: Stage
    score: int
    qualification: Qualification
    signals: LeadSignals
    need_summary: str | None
    product_interest: tuple[str, ...]
    bot_turns_without_progress: int


@dataclass(frozen=True, slots=True)
class TurnFacts:
    kb_best_score: float | None
    min_score: float
    competitor_mentioned: bool
    known_products: Collection[str]


@dataclass(frozen=True, slots=True)
class QualifierDecision:
    stage_path: tuple[Stage, ...]
    rejected_reason: str | None
    qualification: Qualification
    signals: LeadSignals
    need_summary: str | None
    product_interest: tuple[str, ...]
    score: int
    bot_turns_without_progress: int
    hits: tuple[TriggerHit, ...]

    @property
    def final_stage(self) -> Stage | None:
        return self.stage_path[-1] if self.stage_path else None


def decide(
    state: LeadState, output: QualifierOutput, facts: TurnFacts, cfg: TriggerSettings
) -> QualifierDecision:
    qualification = merge_qualification(state.qualification, output.qualification)
    signals = update_signals(state.signals, output, callback_requested=False)
    need = (output.need_summary or "").strip() or state.need_summary
    products = _products(state.product_interest, output.product_interest, facts.known_products)
    path, rejected = qualifier_path(state.stage, Stage(output.proposed_stage))
    score = compute_score(
        ScoreInputs(
            has_need=bool(need),
            has_product=bool(products),
            timeline=qualification.timeline,
            decision_role=qualification.decision_role,
            asked_price=signals.asked_price,
            requested_contact=signals.requested_contact,
            negative=output.sentiment == "negative",
        )
    )
    progressed = bool(path) or score > state.score
    turns = 0 if progressed else state.bot_turns_without_progress + 1
    crossed = state.score < cfg.high_score_threshold <= score
    hits = evaluate(
        TriggerSignals(
            intent=output.intent,
            sentiment=output.sentiment,
            kb_best_score=facts.kb_best_score,
            min_score=facts.min_score,
            bot_turns_without_progress=turns if turns == cfg.no_progress_turns else 0,
            competitor_mentioned=facts.competitor_mentioned,
            score=score if crossed else 0,
            recommend_escalation=output.recommend_escalation,
            confidence=output.confidence,
        ),
        cfg,
    )
    return QualifierDecision(
        stage_path=path,
        rejected_reason=rejected,
        qualification=qualification,
        signals=signals,
        need_summary=need,
        product_interest=products,
        score=score,
        bot_turns_without_progress=turns,
        hits=tuple(hits),
    )


def _products(
    current: tuple[str, ...], proposed: list[str], known: Collection[str]
) -> tuple[str, ...]:
    """Только существующие ключи продуктов; модель не может добавить свой."""
    merged = dict.fromkeys([*current, *(p for p in proposed if p in known)])
    return tuple(merged)[:MAX_PRODUCTS]
