"""Конфигурации полнотекстового поиска PostgreSQL по языку (ADR-0007)."""

import re
from typing import Final

from app.domain.language import Language
from app.domain.text import normalize_question

TS_CONFIG: Final[dict[Language, str]] = {"ru": "russian", "en": "english", "uz": "simple"}

# ts_rank_cd: 1 — делить на 1+log(длина документа), 4 — на среднее расстояние между совпадениями.
RANK_NORMALIZATION: Final = 1 | 4

_WORD = re.compile(r"[\w']+", re.UNICODE)


def ts_config(language: Language) -> str:
    return TS_CONFIG[language]


def query_terms(text: str, max_terms: int = 32) -> list[str]:
    """Нормализованные слова запроса без дублей (порядок сохранён), не длиннее `max_terms`."""
    seen: dict[str, None] = {}
    for word in _WORD.findall(normalize_question(text)):
        if len(word) > 1:
            seen.setdefault(word.strip("'"), None)
    return [w for w in seen if w][:max_terms]
