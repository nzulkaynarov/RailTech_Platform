"""Нарезка DoclingDocument на чанки по структуре документа (PLAN Фаза 1, ADR-0011).

Используется `HybridChunker` из docling-core (иерархия заголовков + ограничение
размера, заголовок таблицы повторяется в каждом её чанке). Токены считаются
офлайн-оценкой: точный токенизатор провайдера embedding недоступен локально,
а размер чанка нужен лишь приблизительно.
"""

import math
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

from docling_core.transforms.chunker.hierarchical_chunker import ChunkingDocSerializer
from docling_core.transforms.chunker.hybrid_chunker import HybridChunker
from docling_core.transforms.chunker.tokenizer.base import BaseTokenizer
from docling_core.transforms.serializer.base import BaseDocSerializer, BaseSerializerProvider
from docling_core.transforms.serializer.markdown import MarkdownTableSerializer
from docling_core.types.doc import DoclingDocument

MAX_CHUNK_TOKENS: Final = 500
HEADING_SEPARATOR: Final = " > "

_PIECES = re.compile(r"\w+|[^\w\s]", re.UNICODE)


def estimate_tokens(text: str) -> int:
    """≈ токены BPE: слово ~ ceil(len/4) токенов, знак препинания — 1."""
    return sum(
        math.ceil(len(p) / 4) if p[0].isalnum() or p[0] == "_" else 1 for p in _PIECES.findall(text)
    )


class ApproxTokenizer(BaseTokenizer):
    max_tokens: int = MAX_CHUNK_TOKENS

    def count_tokens(self, text: str) -> int:
        return estimate_tokens(text)

    def get_max_tokens(self) -> int:
        return self.max_tokens

    def get_tokenizer(self) -> Callable[[str], int]:
        return estimate_tokens


class MarkdownTablesProvider(BaseSerializerProvider):
    """Таблицы в чанках — markdown-таблицы (читаемо для модели и в CRM), а не тройки."""

    def get_serializer(self, doc: DoclingDocument) -> BaseDocSerializer:
        return ChunkingDocSerializer(doc=doc, table_serializer=MarkdownTableSerializer())


@dataclass(frozen=True, slots=True)
class ChunkDraft:
    position: int
    heading_path: str | None
    content: str
    token_count: int

    @property
    def text_for_embedding(self) -> str:
        return f"{self.heading_path}\n{self.content}" if self.heading_path else self.content


def chunk_document(
    document: DoclingDocument, max_tokens: int = MAX_CHUNK_TOKENS
) -> list[ChunkDraft]:
    chunker = HybridChunker(
        tokenizer=ApproxTokenizer(max_tokens=max_tokens),
        merge_peers=True,
        serializer_provider=MarkdownTablesProvider(),
    )
    drafts: list[ChunkDraft] = []
    for chunk in chunker.chunk(document):
        content = chunk.text.strip()
        if not content:
            continue
        headings = getattr(chunk.meta, "headings", None) or []
        heading_path = HEADING_SEPARATOR.join(h.strip() for h in headings if h.strip()) or None
        drafts.append(
            ChunkDraft(
                position=len(drafts),
                heading_path=heading_path,
                content=content,
                token_count=estimate_tokens(content),
            )
        )
    return drafts
