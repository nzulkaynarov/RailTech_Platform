"""Администрирование базы знаний (PLAN Фаза 5, сценарий C4): документы, пробелы, продукты.

Загрузка идёт через API (multipart, ≤ 25 МБ) в S3, индексация — задачей в фоне.
Каждая мутация — с записью в `audit_log`.
"""

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.errors import ConflictError, NotFoundError, ValidationFailedError
from app.domain.language import Language
from app.models.kb import KbChunk, KbDocument, KbGap, Product
from app.repositories import kb as repo
from app.security import audit
from app.security.audit import Actor
from app.services.kb.ingest import KbIngestService, NewKbFile

MAX_UPLOAD_BYTES = 25 * 1024 * 1024
ALLOWED_SUFFIXES = (".pdf", ".docx", ".pptx", ".xlsx", ".md", ".html", ".htm", ".txt")
Enqueue = Callable[[int], Awaitable[object]]


@dataclass(frozen=True, slots=True)
class DocumentPatch:
    title: str | None = None
    is_active: bool | None = None
    product_key: str | None = None
    clear_product: bool = False


class KbAdminService:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        ingest: KbIngestService,
        enqueue: Enqueue,
    ) -> None:
        self._sessions = sessions
        self._ingest = ingest
        self._enqueue = enqueue

    async def upload(self, actor: Actor, file: NewKbFile, gap_id: int | None = None) -> int:
        _check_file(file.filename, len(file.content))
        await self._check_product(file.product_key)
        document_id = await self._ingest.register_file(file)
        async with self._sessions() as session, session.begin():
            await audit.record(
                session,
                actor,
                "kb.upload",
                "kb_document",
                document_id,
                after={"title": file.title, "language": file.language, "product": file.product_key},
            )
            if gap_id is not None:
                await _resolve_gap(session, actor, gap_id, document_id)
        await self._enqueue(document_id)
        return document_id

    async def create_manual(
        self,
        actor: Actor,
        title: str,
        markdown: str,
        language: Language,
        product_key: str | None,
        gap_id: int | None,
    ) -> int:
        """Ручной Markdown-документ (например, ответ на пробел KB)."""
        if not markdown.strip():
            raise ValidationFailedError("document text is empty", field="markdown")
        body = markdown if markdown.lstrip().startswith("#") else f"# {title}\n\n{markdown}"
        file = NewKbFile(
            title=title,
            filename="manual.md",
            content=body.encode("utf-8"),
            language=language,
            product_key=product_key,
            uploaded_by=actor.user_id,
            mime="text/markdown",
        )
        document_id = await self.upload(actor, file, gap_id)
        async with self._sessions() as session, session.begin():
            await session.execute(
                update(KbDocument).where(KbDocument.id == document_id).values(source_type="manual")
            )
        return document_id

    async def update(self, actor: Actor, document_id: int, patch: DocumentPatch) -> None:
        if patch.product_key:
            await self._check_product(patch.product_key)
        async with self._sessions() as session, session.begin():
            document = await _document(session, document_id)
            before = _doc_audit(document)
            if patch.title is not None:
                document.title = patch.title.strip()[:500]
            if patch.is_active is not None:
                document.is_active = patch.is_active
            if patch.clear_product:
                document.product_key = None
            elif patch.product_key is not None:
                document.product_key = patch.product_key
            await audit.record(
                session,
                actor,
                "kb.update",
                "kb_document",
                document_id,
                before=before,
                after=_doc_audit(document),
            )

    async def reingest(self, actor: Actor, document_id: int) -> None:
        async with self._sessions() as session, session.begin():
            document = await _document(session, document_id)
            if document.ingest_status == "processing":
                raise ConflictError("document is being indexed")
            document.ingest_status, document.ingest_error = "pending", None
            await audit.record(session, actor, "kb.reingest", "kb_document", document_id)
        await self._enqueue(document_id)

    async def ignore_gap(self, actor: Actor, gap_id: int) -> None:
        async with self._sessions() as session, session.begin():
            gap = await _gap(session, gap_id)
            gap.status, gap.resolved_by = "ignored", actor.user_id
            await audit.record(session, actor, "kb.gap_ignore", "kb_gap", gap_id)

    async def resolve_gap(self, actor: Actor, gap_id: int, document_id: int) -> None:
        async with self._sessions() as session, session.begin():
            await _document(session, document_id)
            await _resolve_gap(session, actor, gap_id, document_id)

    async def reopen_gap(self, actor: Actor, gap_id: int) -> None:
        async with self._sessions() as session, session.begin():
            gap = await _gap(session, gap_id)
            gap.status, gap.resolved_document_id = "open", None
            await audit.record(session, actor, "kb.gap_reopen", "kb_gap", gap_id)

    async def upsert_product(
        self, actor: Actor, key: str, name: str, description: str | None, is_active: bool
    ) -> None:
        async with self._sessions() as session, session.begin():
            await repo.upsert_product(session, key, name, description)
            await session.execute(
                update(Product).where(Product.key == key).values(is_active=is_active)
            )
            await audit.record(
                session,
                actor,
                "kb.product",
                "product",
                key,
                after={"name": name, "is_active": is_active},
            )

    async def _check_product(self, key: str | None) -> None:
        if key is None:
            return
        async with self._sessions() as session:
            if await session.get(Product, key) is None:
                raise ValidationFailedError("unknown product", field="product_key")


async def list_documents(session: AsyncSession, active: bool | None) -> Sequence[KbDocument]:
    stmt = select(KbDocument).order_by(KbDocument.id.desc())
    if active is not None:
        stmt = stmt.where(KbDocument.is_active.is_(active))
    return (await session.scalars(stmt)).all()


async def list_chunks(session: AsyncSession, document_id: int) -> Sequence[KbChunk]:
    stmt = select(KbChunk).where(KbChunk.document_id == document_id).order_by(KbChunk.position)
    return (await session.scalars(stmt)).all()


async def list_gaps(
    session: AsyncSession, status: str, language: str | None, limit: int, offset: int
) -> tuple[Sequence[KbGap], int]:
    stmt = select(KbGap).where(KbGap.status == status)
    if language:
        stmt = stmt.where(KbGap.language == language)
    total = int(await session.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
    rows = (
        await session.scalars(
            stmt.order_by(KbGap.occurrences.desc(), KbGap.id.desc()).limit(limit).offset(offset)
        )
    ).all()
    return rows, total


async def _resolve_gap(session: AsyncSession, actor: Actor, gap_id: int, document_id: int) -> None:
    gap = await _gap(session, gap_id)
    gap.status, gap.resolved_document_id, gap.resolved_by = "resolved", document_id, actor.user_id
    await audit.record(
        session, actor, "kb.gap_resolve", "kb_gap", gap_id, after={"document_id": document_id}
    )


async def _document(session: AsyncSession, document_id: int) -> KbDocument:
    document = await session.get(KbDocument, document_id, with_for_update=True)
    if document is None:
        raise NotFoundError("kb document not found")
    return document


async def _gap(session: AsyncSession, gap_id: int) -> KbGap:
    gap = await session.get(KbGap, gap_id, with_for_update=True)
    if gap is None:
        raise NotFoundError("kb gap not found")
    return gap


def _check_file(filename: str, size: int) -> None:
    if not filename.lower().endswith(ALLOWED_SUFFIXES):
        raise ValidationFailedError("unsupported file type", field="file")
    if size == 0 or size > MAX_UPLOAD_BYTES:
        raise ValidationFailedError("file must be 1 byte .. 25 MB", field="file")


def _doc_audit(document: KbDocument) -> dict[str, object]:
    return {
        "title": document.title,
        "is_active": document.is_active,
        "product_key": document.product_key,
    }
