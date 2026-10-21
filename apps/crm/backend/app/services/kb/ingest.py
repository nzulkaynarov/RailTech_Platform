"""Ингест документов базы знаний (PLAN Фаза 1, задача 3; ADR-0011).

S3 → Markdown-конвертер → HybridChunker → embeddings → атомарная замена чанков.
Идемпотентен по версии: документ с `indexed_version == version` не переиндексируется
без `force=True`. Ошибка помечает документ `failed`; ретраи — у задачи Procrastinate.
"""

import hashlib
import mimetypes
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import PurePath
from typing import Protocol

import structlog
from docling_core.types.doc import DoclingDocument
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.language import Language
from app.models.kb import KbDocument
from app.repositories import kb as repo
from app.services.kb.chunking import chunk_document

logger = structlog.get_logger(__name__)


class Storage(Protocol):
    async def put(self, bucket: str, key: str, data: bytes, content_type: str) -> None: ...
    async def get(self, bucket: str, key: str) -> bytes: ...


class Converter(Protocol):
    async def convert(self, filename: str, content: bytes, mime: str) -> DoclingDocument: ...


class DocumentEmbedder(Protocol):
    async def embed_documents(
        self, texts: Sequence[tuple[str, str | None]]
    ) -> list[list[float]]: ...


@dataclass(frozen=True, slots=True)
class NewKbFile:
    title: str
    filename: str
    content: bytes
    language: Language
    product_key: str | None = None
    uploaded_by: int | None = None
    mime: str | None = None


class KbIngestService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        storage: Storage,
        converter: Converter,
        embedder: DocumentEmbedder,
        bucket: str,
    ) -> None:
        self._sessions = session_factory
        self._storage = storage
        self._converter = converter
        self._embedder = embedder
        self._bucket = bucket

    async def register_file(self, file: NewKbFile) -> int:
        """Сохраняет файл в S3 и создаёт `kb_documents` (pending). Возвращает id."""
        mime = file.mime or mimetypes.guess_type(file.filename)[0] or "application/octet-stream"
        async with self._sessions() as session, session.begin():
            document = KbDocument(
                title=file.title.strip()[:500],
                product_key=file.product_key,
                language=file.language,
                source_type="file",
                mime=mime,
                content_sha256=hashlib.sha256(file.content).hexdigest(),
                uploaded_by=file.uploaded_by,
            )
            session.add(document)
            await session.flush()
            document.storage_key = f"kb/{document.id}/v1/{_safe_name(file.filename)}"
            await self._storage.put(self._bucket, document.storage_key, file.content, mime)
            return document.id

    async def ingest(self, document_id: int, *, force: bool = False) -> int:
        """Индексирует документ; возвращает число чанков (0 — пропущен/пуст)."""
        log = logger.bind(kb_document_id=document_id)
        async with self._sessions() as session, session.begin():
            document = await repo.get_document(session, document_id)
            if document is None:
                log.warning("kb_ingest_document_missing")
                return 0
            if not force and document.indexed_version == document.version:
                log.info("kb_ingest_skipped_up_to_date")
                return document.chunk_count
            if document.storage_key is None:
                raise ValueError(f"kb document {document_id} has no stored file")
            await repo.mark_ingest(session, document_id, "processing")
            title, key, mime = document.title, document.storage_key, document.mime
        try:
            chunks = await self._build_chunks(title, key, mime or "application/octet-stream")
        except Exception as exc:
            async with self._sessions() as session, session.begin():
                await repo.mark_ingest(session, document_id, "failed", repr(exc)[:2000])
            log.exception("kb_ingest_failed")
            raise
        async with self._sessions() as session, session.begin():
            document = await repo.get_document(session, document_id)
            if document is None:
                return 0
            await repo.replace_chunks(session, document, chunks)
        log.info("kb_ingest_done", chunks=len(chunks))
        return len(chunks)

    async def _build_chunks(self, title: str, key: str, mime: str) -> list[repo.NewChunk]:
        content = await self._storage.get(self._bucket, key)
        document = await self._converter.convert(PurePath(key).name, content, mime)
        drafts = chunk_document(document)
        vectors = await self._embedder.embed_documents(
            [(d.text_for_embedding, title) for d in drafts]
        )
        return [
            repo.NewChunk(
                position=d.position,
                heading_path=d.heading_path,
                content=d.content,
                token_count=d.token_count,
                embedding=v,
            )
            for d, v in zip(drafts, vectors, strict=True)
        ]


def _safe_name(filename: str) -> str:
    name = PurePath(filename).name
    return "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in name)[:200] or "file"
