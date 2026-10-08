"""Доступ к таблицам базы знаний и гибридный поиск (ADR-0007)."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from sqlalchemy import ColumnElement, delete, func, literal, select, text, update
from sqlalchemy.dialects.postgresql import REGCONFIG, insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.kb import KbChunk, KbDocument, KbGap, Product

CANDIDATES: Final = 20


@dataclass(frozen=True, slots=True)
class ChunkHit:
    chunk_id: int
    document_id: int
    document_title: str
    product_key: str | None
    heading_path: str | None
    content: str
    similarity: float | None


@dataclass(frozen=True, slots=True)
class NewChunk:
    position: int
    heading_path: str | None
    content: str
    token_count: int
    embedding: list[float]


async def get_document(session: AsyncSession, document_id: int) -> KbDocument | None:
    return await session.get(KbDocument, document_id)


async def list_products(session: AsyncSession) -> Sequence[Product]:
    result = await session.scalars(select(Product).where(Product.is_active).order_by(Product.key))
    return result.all()


async def replace_chunks(
    session: AsyncSession, document: KbDocument, chunks: Sequence[NewChunk]
) -> None:
    """Атомарная замена чанков документа (идемпотентный переингест)."""
    await session.execute(delete(KbChunk).where(KbChunk.document_id == document.id))
    session.add_all(
        KbChunk(
            document_id=document.id,
            language=document.language,
            position=c.position,
            heading_path=c.heading_path,
            content=c.content,
            token_count=c.token_count,
            embedding=c.embedding,
        )
        for c in chunks
    )
    document.chunk_count = len(chunks)
    document.indexed_version = document.version
    document.ingest_status = "done"
    document.ingest_error = None


def _base_filter(product_key: str | None) -> list[ColumnElement[bool]]:
    conditions: list[ColumnElement[bool]] = [
        KbDocument.is_active.is_(True),
        KbDocument.ingest_status == "done",
    ]
    if product_key:
        conditions.append(KbDocument.product_key == product_key)
    return conditions


async def vector_candidates(
    session: AsyncSession, embedding: list[float], product_key: str | None, limit: int = CANDIDATES
) -> list[tuple[int, float]]:
    """(chunk_id, косинусная близость) по убыванию близости."""
    await session.execute(text("SET LOCAL hnsw.ef_search = 100"))
    await session.execute(text("SET LOCAL hnsw.iterative_scan = relaxed_order"))
    distance = KbChunk.embedding.cosine_distance(embedding)
    stmt = (
        select(KbChunk.id, (1 - distance).label("similarity"))
        .join(KbDocument, KbDocument.id == KbChunk.document_id)
        .where(*_base_filter(product_key))
        .order_by(distance)
        .limit(limit)
    )
    rows = (await session.execute(stmt)).all()
    return [(row.id, float(row.similarity)) for row in rows]


async def fulltext_candidates(
    session: AsyncSession,
    terms: Sequence[str],
    ts_config: str,
    product_key: str | None,
    rank_normalization: int,
    limit: int = CANDIDATES,
) -> list[int]:
    """chunk_id по убыванию ts_rank_cd; запрос — OR слов (ADR-0007)."""
    if not terms:
        return []
    config = literal(ts_config, REGCONFIG)
    query = func.to_tsquery(config, " | ".join(_quote_term(t) for t in terms))
    rank = func.ts_rank_cd(KbChunk.tsv, query, rank_normalization)
    stmt = (
        select(KbChunk.id)
        .join(KbDocument, KbDocument.id == KbChunk.document_id)
        .where(*_base_filter(product_key), KbChunk.tsv.op("@@")(query))
        .order_by(rank.desc(), KbChunk.id)
        .limit(limit)
    )
    return list((await session.scalars(stmt)).all())


def _quote_term(term: str) -> str:
    """Слово как лексема tsquery: экранирование кавычек, без операторов."""
    return "'" + term.replace("\\", "").replace("'", "''") + "'"


async def load_hits(session: AsyncSession, chunk_ids: Sequence[int]) -> dict[int, ChunkHit]:
    stmt = (
        select(KbChunk, KbDocument.title, KbDocument.product_key)
        .join(KbDocument, KbDocument.id == KbChunk.document_id)
        .where(KbChunk.id.in_(chunk_ids))
    )
    hits: dict[int, ChunkHit] = {}
    for chunk, title, product_key in (await session.execute(stmt)).all():
        hits[chunk.id] = ChunkHit(
            chunk_id=chunk.id,
            document_id=chunk.document_id,
            document_title=title,
            product_key=product_key,
            heading_path=chunk.heading_path,
            content=chunk.content,
            similarity=None,
        )
    return hits


async def upsert_gap(
    session: AsyncSession,
    *,
    question: str,
    normalized: str,
    language: str,
    best_score: float | None,
    lead_id: int | None,
) -> int:
    """Регистрирует пробел KB или увеличивает `occurrences` (SPEC §7.1 fallback)."""
    base = insert(KbGap).values(
        question=question,
        question_normalized=normalized,
        language=language,
        best_score=best_score,
        lead_id=lead_id,
    )
    stmt = base.on_conflict_do_update(
        index_elements=[KbGap.question_normalized],
        set_={
            "occurrences": KbGap.occurrences + 1,
            "best_score": func.greatest(KbGap.best_score, base.excluded.best_score),
            "status": text("CASE WHEN kb_gaps.status = 'ignored' THEN 'ignored' ELSE 'open' END"),
        },
    ).returning(KbGap.id)
    gap_id: int = (await session.execute(stmt)).scalar_one()
    return gap_id


async def mark_ingest(
    session: AsyncSession, document_id: int, status: str, error: str | None = None
) -> None:
    stmt = update(KbDocument).where(KbDocument.id == document_id)
    await session.execute(stmt.values(ingest_status=status, ingest_error=error))


async def upsert_product(
    session: AsyncSession, key: str, name: str, description: str | None
) -> None:
    stmt = insert(Product).values(key=key, name=name, description=description)
    await session.execute(
        stmt.on_conflict_do_update(
            index_elements=[Product.key], set_={"name": name, "description": description}
        )
    )


async def find_document_by_title(session: AsyncSession, title: str) -> KbDocument | None:
    stmt = select(KbDocument).where(KbDocument.title == title).order_by(KbDocument.id.desc())
    return (await session.scalars(stmt)).first()
