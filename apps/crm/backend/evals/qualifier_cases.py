"""Схема кейсов квалификатора (`evals/qualifier/*.yaml`) и детерминированная часть прогона."""

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from app.domain.keywords import find_terms
from app.domain.triggers import TriggerSignals
from app.schemas.settings import AppSettings

QUALIFIER_DIR = Path(__file__).parent / "qualifier"
PRODUCTS_FILE = Path(__file__).parent / "fixtures" / "kb" / "products.yaml"

Stage = Literal["new", "engaged", "qualified"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class QExpect(_Strict):
    escalate: bool
    triggers: list[str] = Field(default_factory=list, description="должны быть среди сработавших")
    stage: Stage


class QualifierCase(_Strict):
    id: str = Field(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")
    category: str
    language: Literal["ru", "uz", "en"]
    stage: Stage = "engaged"
    score: int = 0
    bot_turns_without_progress: int = 0
    kb_best_score: float | None = 0.8
    transcript: list[tuple[Literal["lead", "bot"], str]] = Field(min_length=1)
    expect: QExpect


def load_qualifier_cases(directory: Path = QUALIFIER_DIR) -> list[QualifierCase]:
    cases: list[QualifierCase] = []
    for path in sorted(directory.glob("*.yaml")):
        cases += [
            QualifierCase.model_validate(raw) for raw in yaml.safe_load(path.read_text("utf-8"))
        ]
    return cases


def load_products() -> list[tuple[str, str]]:
    return [(p["key"], p["name"]) for p in yaml.safe_load(PRODUCTS_FILE.read_text("utf-8"))]


def turn_signals(case: QualifierCase, cfg: AppSettings) -> TriggerSignals:
    """Триггеры, которые в системе срабатывают кодом в ходе диалога (без модели)."""
    last = next(text for role, text in reversed(case.transcript) if role == "lead")
    return TriggerSignals(
        human_requested=bool(find_terms(last, cfg.escalation.human_request_terms)),
        stop_word_hit=bool(find_terms(last, cfg.stop_words.terms)),
    )
