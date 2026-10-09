"""Профиль embedding-модели: размерность и форматирование текста (ADR-0004).

`gemini-embedding-2` не поддерживает `task_type`, задача передаётся префиксом.
Смена модели embedding = новый профиль + переиндексация KB.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True, slots=True)
class EmbeddingProfile:
    dimensions: int
    query_template: str
    document_template: str

    def format_query(self, text: str) -> str:
        return self.query_template.format(text=text.strip())

    def format_document(self, text: str, title: str | None) -> str:
        return self.document_template.format(title=(title or "none").strip(), text=text.strip())


GEMINI_EMBEDDING_2: Final = EmbeddingProfile(
    dimensions=1536,
    query_template="task: search result | query: {text}",
    document_template="title: {title} | text: {text}",
)

ACTIVE_PROFILE: Final = GEMINI_EMBEDDING_2


def l2_normalize(vector: Sequence[float]) -> list[float]:
    """Единичная длина: косинус = скалярное произведение; нулевой вектор — ошибка."""
    norm = math.sqrt(math.fsum(x * x for x in vector))
    if norm == 0 or not math.isfinite(norm):
        raise ValueError("cannot normalize a zero or non-finite vector")
    return [x / norm for x in vector]
