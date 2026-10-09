"""Гибридный поиск по базе знаний: вектор + BM25 → RRF → порог по косинусу (ADR-0007)."""

from dataclasses import dataclass
from typing import Final, Protocol

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.fulltext import RANK_NORMALIZATION, query_terms, ts_config
from app.domain.language import Language, detect_language
from app.domain.rrf import reciprocal_rank_fusion
from app.repositories import kb as repo

DEFAULT_TOP_K: Final = 6
DEFAULT_MIN_SCORE: Final = 0.55


class QueryEmbedder(Protocol):
    async def embed_query(self, text: str) -> list[float]: ...


@dataclass(frozen=True, slots=True)
class SearchHit:
    chunk_id: int
    document_id: int
    document_title: str
    product_key: str | None
    heading_path: str | None
    content: str
    similarity: float | None
    rrf_score: float


@dataclass(frozen=True, slots=True)
class SearchResult:
    hits: list[SearchHit]
    best_score: float | None
    language: Language

    def is_confident(self, min_score: float) -> bool:
        return self.best_score is not None and self.best_score >= min_score


class KbSearchService:
    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession], embedder: QueryEmbedder
    ) -> None:
        self._sessions = session_factory
        self._embedder = embedder

    async def search(
        self,
        query: str,
        *,
        product_key: str | None = None,
        top_k: int = DEFAULT_TOP_K,
        language: Language | None = None,
    ) -> SearchResult:
        lang = language or detect_language(query)
        embedding = await self._embedder.embed_query(query)
        async with self._sessions() as session, session.begin():
            vector = await repo.vector_candidates(session, embedding, product_key)
            fulltext = await repo.fulltext_candidates(
                session, query_terms(query), ts_config(lang), product_key, RANK_NORMALIZATION
            )
            fused = reciprocal_rank_fusion([[cid for cid, _ in vector], fulltext], limit=top_k)
            loaded = await repo.load_hits(session, [item.key for item in fused])
        similarity = dict(vector)
        hits = [
            _to_hit(loaded[item.key], similarity.get(item.key), item.score)
            for item in fused
            if item.key in loaded
        ]
        scores = [h.similarity for h in hits if h.similarity is not None]
        return SearchResult(hits=hits, best_score=max(scores, default=None), language=lang)


def _to_hit(hit: repo.ChunkHit, similarity: float | None, rrf: float) -> SearchHit:
    return SearchHit(
        chunk_id=hit.chunk_id,
        document_id=hit.document_id,
        document_title=hit.document_title,
        product_key=hit.product_key,
        heading_path=hit.heading_path,
        content=hit.content,
        similarity=similarity,
        rrf_score=rrf,
    )
