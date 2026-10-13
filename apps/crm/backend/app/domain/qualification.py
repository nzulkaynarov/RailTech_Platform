"""Типы вывода квалификатора (SPEC §7.2). Модель предлагает, код решает."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Timeline = Literal["<1m", "<3m", "<12m", ">12m"]
DecisionRole = Literal["decision_maker", "influencer", "researcher"]
Intent = Literal[
    "info",
    "compare",
    "pricing",
    "request_contact",
    "complaint",
    "service",
    "document",
    "smalltalk",
    "other",
]
Sentiment = Literal["positive", "neutral", "negative"]


class Qualification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    budget_hint: str | None = None
    timeline: Timeline | None = None
    decision_role: DecisionRole | None = None
    company: str | None = None
    company_size: str | None = None
    region: str | None = None


class QualifierOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    need_summary: str | None = None
    product_interest: list[str] = Field(default_factory=list)
    intent: Intent
    sentiment: Sentiment
    qualification: Qualification = Field(default_factory=Qualification)
    proposed_stage: Literal["new", "engaged", "qualified"]
    recommend_escalation: bool = False
    escalation_reason: str | None = None
    confidence: float = Field(ge=0, le=1)
    next_best_action: str = ""


class LeadSignals(BaseModel):
    """Накопленные «липкие» сигналы лида (хранятся в `leads.qualification.signals`)."""

    model_config = ConfigDict(extra="forbid")

    asked_price: bool = False
    requested_contact: bool = False


def merge_qualification(current: Qualification, update: Qualification) -> Qualification:
    """Новые непустые значения перекрывают старые; пустые не стирают известное."""
    merged = current.model_dump()
    merged.update({k: v for k, v in update.model_dump().items() if v not in (None, "")})
    return Qualification.model_validate(merged)


def update_signals(
    signals: LeadSignals, output: QualifierOutput, callback_requested: bool
) -> LeadSignals:
    return LeadSignals(
        asked_price=signals.asked_price or output.intent == "pricing",
        requested_contact=signals.requested_contact
        or output.intent == "request_contact"
        or callback_requested,
    )
