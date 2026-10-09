"""Триггеры эскалации (SPEC §8.1). Параметры — `settings.escalation`."""

from collections.abc import Collection
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final

from app.domain.qualification import Intent, Sentiment


class Priority(StrEnum):
    HOT = "hot"
    WARM = "warm"
    INFO = "info"


PRIORITY_ORDER: Final = {Priority.INFO: 0, Priority.WARM: 1, Priority.HOT: 2}


class TriggerCode(StrEnum):
    HUMAN_REQUESTED = "human_requested"
    CALLBACK_REQUESTED = "callback_requested"
    PRICE_OR_CONTRACT_ASKED = "price_or_contract_asked"
    NEGATIVE_SENTIMENT = "negative_sentiment"
    COMPLAINT = "complaint"
    KB_GAP_STREAK = "kb_gap_streak"
    NO_PROGRESS = "no_progress"
    COMPETITOR_MENTIONED = "competitor_mentioned"
    HIGH_SCORE = "high_score"
    QUALIFIER_RECOMMEND = "qualifier_recommend"
    DOCUMENT_NOT_FOUND = "document_not_found"
    SERVICE_REQUEST = "service_request"
    ATTACHMENT_RECEIVED = "attachment_received"
    # Сбои, о которых лиду сказали «коллеги увидят», — команда должна увидеть (аудит P-11, P-12).
    AGENT_UNAVAILABLE = "agent_unavailable"
    DELIVERY_FAILED = "delivery_failed"


PRIORITY: Final[dict[TriggerCode, Priority]] = {
    TriggerCode.HUMAN_REQUESTED: Priority.HOT,
    TriggerCode.CALLBACK_REQUESTED: Priority.HOT,
    TriggerCode.PRICE_OR_CONTRACT_ASKED: Priority.HOT,
    TriggerCode.NEGATIVE_SENTIMENT: Priority.HOT,
    TriggerCode.COMPLAINT: Priority.HOT,
    TriggerCode.KB_GAP_STREAK: Priority.WARM,
    TriggerCode.NO_PROGRESS: Priority.WARM,
    TriggerCode.COMPETITOR_MENTIONED: Priority.WARM,
    TriggerCode.HIGH_SCORE: Priority.WARM,
    TriggerCode.QUALIFIER_RECOMMEND: Priority.WARM,
    TriggerCode.DOCUMENT_NOT_FOUND: Priority.WARM,
    TriggerCode.SERVICE_REQUEST: Priority.INFO,
    TriggerCode.ATTACHMENT_RECEIVED: Priority.INFO,
    TriggerCode.AGENT_UNAVAILABLE: Priority.INFO,
    TriggerCode.DELIVERY_FAILED: Priority.INFO,
}


@dataclass(frozen=True, slots=True)
class TriggerSettings:
    high_score_threshold: int = 70
    no_progress_turns: int = 4
    kb_gap_streak: int = 2
    qualifier_min_confidence: float = 0.7
    disabled: frozenset[TriggerCode] = field(default_factory=frozenset)


@dataclass(frozen=True, slots=True)
class TriggerSignals:
    intent: Intent | None = None
    sentiment: Sentiment | None = None
    human_requested: bool = False
    callback_requested: bool = False
    stop_word_hit: bool = False
    kb_best_score: float | None = None
    min_score: float = 0.55
    consecutive_fallbacks: int = 0
    bot_turns_without_progress: int = 0
    competitor_mentioned: bool = False
    score: int = 0
    recommend_escalation: bool = False
    confidence: float = 0.0
    customer_mode: bool = False
    document_not_found: bool = False
    attachment_received: bool = False
    agent_unavailable: bool = False
    delivery_failed: bool = False


@dataclass(frozen=True, slots=True)
class TriggerHit:
    code: TriggerCode
    priority: Priority


def evaluate(signals: TriggerSignals, settings: TriggerSettings) -> list[TriggerHit]:
    """Сработавшие триггеры в порядке убывания приоритета (стабильно по таблице)."""
    fired = [code for code in TriggerCode if _fires(code, signals, settings)]
    hits = [TriggerHit(code, PRIORITY[code]) for code in fired if code not in settings.disabled]
    return sorted(hits, key=lambda h: -PRIORITY_ORDER[h.priority])


def max_priority(priorities: Collection[Priority]) -> Priority | None:
    return max(priorities, key=PRIORITY_ORDER.__getitem__, default=None)


def _fires(code: TriggerCode, s: TriggerSignals, cfg: TriggerSettings) -> bool:
    match code:
        case TriggerCode.HUMAN_REQUESTED:
            return s.human_requested
        case TriggerCode.CALLBACK_REQUESTED:
            return s.callback_requested or s.intent == "request_contact"
        case TriggerCode.PRICE_OR_CONTRACT_ASKED:
            # Бот называет цену только дословно из базы, иначе обещает расчёт менеджера —
            # обещание выполняет код, а не модель (eval-gate 2026-10-09, решение владельца).
            return s.intent == "pricing"
        case TriggerCode.NEGATIVE_SENTIMENT:
            return s.sentiment == "negative" or s.stop_word_hit
        case TriggerCode.COMPLAINT:
            return s.intent == "complaint"
        case TriggerCode.KB_GAP_STREAK:
            return s.consecutive_fallbacks >= cfg.kb_gap_streak
        case TriggerCode.NO_PROGRESS:
            return s.bot_turns_without_progress >= cfg.no_progress_turns
        case TriggerCode.COMPETITOR_MENTIONED:
            return s.competitor_mentioned
        case TriggerCode.HIGH_SCORE:
            return s.score >= cfg.high_score_threshold
        case TriggerCode.QUALIFIER_RECOMMEND:
            return s.recommend_escalation and s.confidence >= cfg.qualifier_min_confidence
        case TriggerCode.DOCUMENT_NOT_FOUND:
            return s.customer_mode and s.document_not_found
        case TriggerCode.SERVICE_REQUEST:
            return s.customer_mode and s.intent == "service"
        case TriggerCode.ATTACHMENT_RECEIVED:
            return s.attachment_received
        case TriggerCode.AGENT_UNAVAILABLE:
            return s.agent_unavailable
        case TriggerCode.DELIVERY_FAILED:
            return s.delivery_failed
