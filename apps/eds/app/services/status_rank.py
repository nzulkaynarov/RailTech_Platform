"""Ранг слова статуса строки списка для порядка по шапке (Х-15б): слово выводится из фактов, как в statusEntry веба."""

from typing import Any

from sqlalchemy import case, literal
from sqlalchemy.sql.elements import ColumnElement

from app.schemas.documents import DocumentKind

#: Слова по порядку пути документа; код вне списка (новый статус) — после всех. «На подписи» — не код, а факт
#: `signing_state.awaiting_signature` (письмо `draft` с запросом регистрации): стоит сразу после черновика.
SIGNING = "signing"
WORD_ORDER = (
    "draft",
    SIGNING,
    "on_approval",
    "open",
    "awaiting_resolution",
    "resolved",
    "in_execution",
    "approved",
    "to_accountant",
    "paid",
    "sent",
    "executed",
    "noted",
    "closed",
    "returned",
    "rejected",
    "duplicate",
)
_RANK = {word: index for index, word in enumerate(WORD_ORDER)}


def rank_of(status: str, awaiting_signature: bool, kind: str) -> int:
    """То же правило для одной строки (тесты и сверка со словом на экране)."""
    if kind == DocumentKind.LETTER_OUT.value and status == "draft" and awaiting_signature:
        return _RANK[SIGNING]
    return _RANK.get(status, len(WORD_ORDER))


def rank_expr(status: Any, awaiting_signature: ColumnElement[bool]) -> ColumnElement[int]:
    """SQL-ранг слова: `awaiting_signature` — факт EDS (signing_state), остальное — код статуса."""
    whens = [(awaiting_signature, literal(_RANK[SIGNING]))]
    whens += [(status == word, literal(index)) for word, index in _RANK.items() if word != SIGNING]
    return case(*whens, else_=literal(len(WORD_ORDER)))
