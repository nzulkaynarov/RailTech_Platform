"""Лента решений по лиду: прогоны квалификатора и переходы стадий (PLAN Фаза 3)."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel


class QualifierRunItem(BaseModel):
    kind: Literal["qualifier"]
    id: int
    at: datetime
    intent: str | None
    sentiment: str | None
    proposed_stage: str | None
    applied_stage: str | None
    rejected_reason: str | None
    score_before: int
    score_after: int
    triggers_fired: list[str]
    escalated: bool
    next_best_action: str | None
    error: str | None
    model: str | None
    cost_usd: float | None
    trace_id: str | None


class TransitionItem(BaseModel):
    kind: Literal["transition"]
    id: int
    at: datetime
    from_stage: str
    to_stage: str
    source: str
    actor_user_id: int | None
    reason: str


class DecisionsResponse(BaseModel):
    lead_id: int
    stage: str
    score: int
    owner_mode: str
    items: list[QualifierRunItem | TransitionItem]


def qualifier_summary(output: dict[str, Any] | None) -> dict[str, Any]:
    output = output or {}
    return {
        "intent": output.get("intent"),
        "sentiment": output.get("sentiment"),
        "next_best_action": output.get("next_best_action"),
    }
