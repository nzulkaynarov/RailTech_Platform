"""Состояние и результат хода диалогового агента (SPEC §7.1)."""

from dataclasses import dataclass, field
from typing import Any, TypedDict

from app.domain.dialog_policy import Action


class DialogState(TypedDict):
    lead_id: int
    text: str
    language: str
    mode: str
    context_token: str
    human_requested: bool
    lead: dict[str, Any] | None
    kb: dict[str, Any] | None
    action: str | None
    clarify: bool
    reason: str
    reply: str | None
    llm: dict[str, Any] | None
    callback_requested: bool
    docs: list[dict[str, Any]] | None
    document: dict[str, Any] | None
    service_request: bool


@dataclass(frozen=True, slots=True)
class DialogResult:
    action: Action
    reply: str | None
    reason: str
    best_score: float | None = None
    kb_hits: list[dict[str, Any]] = field(default_factory=list)
    llm: dict[str, Any] | None = None
    callback_requested: bool = False
    trace_id: str | None = None
    prompt_version: str | None = None
    document: dict[str, Any] | None = None
    service_request: bool = False
    mode: str = "prospect"
    price_quoted: bool = False
