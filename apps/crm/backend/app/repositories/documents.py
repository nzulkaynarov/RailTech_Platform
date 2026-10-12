"""Доступ к документам клиентов. Каждый запрос бота обязан нести `client_id` (SPEC §11).

`client_id` — обязательный позиционный аргумент без значения по умолчанию: забыть
фильтр невозможно на уровне сигнатуры; он берётся только из подписанного контекста.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from sqlalchemy import Select, func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.fulltext import query_terms
from app.models.clients import Document, DocumentAccessLog

MAX_RESULTS = 10


@dataclass(frozen=True, slots=True)
class DocumentFilter:
    doc_type: str | None = None
    date_from: date | None = None
    date_to: date | None = None
    number: str | None = None


def _for_client(client_id: int, *, visible_only: bool) -> Select[Document]:
    if client_id <= 0:
        raise ValueError("client_id is required")
    stmt = select(Document).where(Document.client_id == client_id)
    if visible_only:
        stmt = stmt.where(Document.is_visible_to_client.is_(True))
    return stmt


def visible_for_client(client_id: int) -> Select[Document]:
    """Запрос видимых клиенту документов (меню /docs бота) — тот же фильтр, что у docs-mcp."""
    return _for_client(client_id, visible_only=True)


async def search_for_client(
    session: AsyncSession, client_id: int, text: str, flt: DocumentFilter, limit: int = MAX_RESULTS
) -> Sequence[Document]:
    """Документы клиента для бота: только видимые клиенту, фильтры типа/периода/номера."""
    stmt = _for_client(client_id, visible_only=True)
    if flt.doc_type:
        stmt = stmt.where(Document.type == flt.doc_type)
    if flt.date_from:
        stmt = stmt.where(Document.doc_date >= flt.date_from)
    if flt.date_to:
        stmt = stmt.where(Document.doc_date < flt.date_to)
    if flt.number:
        stmt = stmt.where(func.lower(Document.number) == flt.number.lower())
    terms = query_terms(text)
    rank = (
        func.ts_rank_cd(
            Document.tsv,
            func.to_tsquery("simple", " | ".join(f"'{t.replace(chr(39), '')}'" for t in terms)),
        )
        if terms and not (flt.doc_type or flt.date_from or flt.number)
        else literal(0.0)
    )
    ordered = stmt.order_by(rank.desc(), Document.doc_date.desc().nulls_last(), Document.id.desc())
    return (await session.scalars(ordered.limit(limit))).all()


async def get_for_client(
    session: AsyncSession, client_id: int, document_id: int
) -> Document | None:
    stmt = _for_client(client_id, visible_only=True).where(Document.id == document_id)
    return (await session.scalars(stmt)).first()


async def log_access(
    session: AsyncSession,
    document_id: int,
    by_type: str,
    by_id: int | None,
    tg_user_id: int | None = None,
) -> None:
    session.add(
        DocumentAccessLog(
            document_id=document_id,
            accessed_by_type=by_type,
            accessed_by_id=by_id,
            tg_user_id=tg_user_id,
        )
    )
