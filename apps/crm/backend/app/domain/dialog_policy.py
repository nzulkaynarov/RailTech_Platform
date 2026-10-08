"""Решение диалогового агента на ход (узел `decide`, SPEC §7.1). Решает код."""

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from app.domain.stages import OwnerMode, Stage
from app.domain.text import normalize_question


class Action(StrEnum):
    SILENT = "silent"
    HANDOFF = "handoff"
    DELIVER_DOCUMENT = "deliver_document"
    FALLBACK = "fallback"
    ANSWER = "answer"


EARLY_STAGES: Final = frozenset({Stage.NEW, Stage.ENGAGED})

_SMALLTALK: Final = frozenset(
    {
        "привет",
        "здравствуйте",
        "добрый день",
        "доброе утро",
        "добрый вечер",
        "спасибо",
        "благодарю",
        "ок",
        "окей",
        "хорошо",
        "понятно",
        "пока",
        "до свидания",
        "ясно",
        "salom",
        "assalomu alaykum",
        "rahmat",
        "katta rahmat",
        "xayr",
        "tushunarli",
        "yaxshi",
        "hello",
        "hi",
        "hey",
        "thanks",
        "thank you",
        "ok",
        "okay",
        "bye",
        "good morning",
    }
)
_QUESTION: Final = re.compile(
    r"\?|\b(как|что|сколько|где|когда|можно|есть ли"
    r"|qanday|qancha|nima|qayerda|how|what|where|when|can)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class DecisionInput:
    owner_mode: OwnerMode
    stage: Stage
    text: str
    human_requested: bool
    stop_word_hit: bool
    best_score: float | None
    min_score: float
    need_known: bool
    document_match: bool = False


@dataclass(frozen=True, slots=True)
class Decision:
    action: Action
    clarify: bool = False
    reason: str = ""


def is_smalltalk(text: str) -> bool:
    normalized = normalize_question(text)
    return normalized in _SMALLTALK or (len(normalized.split()) <= 2 and not _QUESTION.search(text))


def decide(inp: DecisionInput) -> Decision:
    if inp.owner_mode != OwnerMode.BOT:
        return Decision(Action.SILENT, reason=f"owner_mode={inp.owner_mode}")
    if inp.human_requested or inp.stop_word_hit:
        return Decision(
            Action.HANDOFF, reason="human_requested" if inp.human_requested else "stop_word"
        )
    if inp.document_match:
        return Decision(Action.DELIVER_DOCUMENT, reason="document_match")
    smalltalk = is_smalltalk(inp.text)
    confident = inp.best_score is not None and inp.best_score >= inp.min_score
    if not confident and not smalltalk:
        return Decision(Action.FALLBACK, reason=f"best_score={inp.best_score} < {inp.min_score}")
    clarify = not inp.need_known and inp.stage in EARLY_STAGES and not smalltalk
    return Decision(Action.ANSWER, clarify=clarify, reason="smalltalk" if smalltalk else "kb")
