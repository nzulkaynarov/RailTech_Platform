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
    # BOT-07: найдено несколько документов клиента — выбор кнопками (id — из поиска кода).
    CHOOSE_DOCUMENT = "choose_document"
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
# Подтверждение/благодарность: короткий ответ из настроек без модели и без встречного вопроса.
# Сообщение целиком из этих слов («понятно, спасибо», «ok thanks», «katta rahmat»).
_ACK_WORDS: Final = frozenset(
    {
        "спасибо",
        "благодарю",
        "ок",
        "окей",
        "хорошо",
        "понятно",
        "ясно",
        "rahmat",
        "tushunarli",
        "yaxshi",
        "xop",
        "mayli",
        "thanks",
        "thank",
        "thx",
        "ok",
        "okay",
        "got",
        "great",
    }
)
_ACK_FILLERS: Final = frozenset(
    {"большое", "огромное", "вам", "katta", "sizga", "you", "it", "so", "much"}
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
    document_requested: bool = False
    documents_found: int = 0
    customer: bool = False
    kb_unavailable: bool = False
    # Сервисный режим (M3-CRM-07): у хода есть инструменты ERP — модель может проверить сама.
    erp_available: bool = False


@dataclass(frozen=True, slots=True)
class Decision:
    action: Action
    clarify: bool = False
    reason: str = ""


def is_smalltalk(text: str) -> bool:
    normalized = normalize_question(text)
    return normalized in _SMALLTALK or (len(normalized.split()) <= 2 and not _QUESTION.search(text))


def is_ack(text: str) -> bool:
    words = normalize_question(text).split()
    return (
        0 < len(words) <= 4
        and any(w in _ACK_WORDS for w in words)
        and all(w in _ACK_WORDS or w in _ACK_FILLERS for w in words)
    )


def decide(inp: DecisionInput) -> Decision:
    if inp.owner_mode != OwnerMode.BOT:
        return Decision(Action.SILENT, reason=f"owner_mode={inp.owner_mode}")
    if inp.human_requested or inp.stop_word_hit:
        return Decision(
            Action.HANDOFF, reason="human_requested" if inp.human_requested else "stop_word"
        )
    if inp.document_match:
        return Decision(Action.DELIVER_DOCUMENT, reason="document_match")
    if inp.document_requested and inp.documents_found == 0:
        if inp.erp_available:
            # В индексе CRM документа нет, а «где мой счёт» знает ERP: ответ по инструментам.
            return Decision(Action.ANSWER, reason="document_lookup_erp")
        # Клиент просит документ, а у него такого нет — честно и сразу к менеджеру (C5).
        return Decision(Action.HANDOFF, reason="document_not_found")
    if inp.document_requested:
        # Несколько кандидатов: выбор кнопками без модели (BOT-07).
        return Decision(Action.CHOOSE_DOCUMENT, reason="documents_ambiguous")
    if is_ack(inp.text):
        return Decision(Action.ANSWER, reason="ack")
    smalltalk = is_smalltalk(inp.text)
    if inp.kb_unavailable and not smalltalk and not inp.customer:
        # Поиск недоступен: честный ответ с предложением менеджера, а не извинение (аудит P0).
        return Decision(Action.FALLBACK, reason="kb_unavailable")
    confident = inp.best_score is not None and inp.best_score >= inp.min_score
    if not confident and not smalltalk and inp.customer:
        # Клиенту отвечает сервисный промпт: без фактов из KB он оформляет запрос менеджеру.
        return Decision(Action.ANSWER, reason="customer_service")
    if not confident and not smalltalk:
        return Decision(Action.FALLBACK, reason=f"best_score={inp.best_score} < {inp.min_score}")
    clarify = not inp.need_known and inp.stage in EARLY_STAGES and not smalltalk
    return Decision(Action.ANSWER, clarify=clarify, reason="smalltalk" if smalltalk else "kb")
