"""Документы клиентов (SPEC §5.6): загрузка, извлечение текста (docling), ссылки с журналом."""

import mimetypes
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date
from pathlib import PurePath
from typing import Protocol

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.errors import NotFoundError, ValidationFailedError
from app.models.clients import Client, Document
from app.repositories import documents as repo
from app.security import audit
from app.security.principal import Principal
from app.services.kb.ingest import Converter, Storage

logger = structlog.get_logger(__name__)

MAX_BYTES = 25 * 1024 * 1024
LINK_TTL_S = 600
TEXT_LIMIT = 500_000
TYPES = ("contract", "proposal", "letter", "invoice", "act", "other")
Enqueue = Callable[[int], Awaitable[object]]


@dataclass(frozen=True, slots=True)
class NewDocument:
    client_id: int
    type: str
    title: str
    filename: str
    content: bytes
    number: str | None = None
    doc_date: date | None = None
    visible: bool = True
    mime: str | None = None


class PresignedStorage(Storage, Protocol):
    async def presigned_get(self, bucket: str, key: str, expires_s: int = LINK_TTL_S) -> str: ...


class DocumentService:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        storage: PresignedStorage,
        converter: Converter,
        bucket: str,
        enqueue: Enqueue,
    ) -> None:
        self._sessions = sessions
        self._storage = storage
        self._converter = converter
        self._bucket = bucket
        self._enqueue = enqueue

    async def upload(self, who: Principal, doc: NewDocument) -> int:
        if doc.type not in TYPES:
            raise ValidationFailedError("unknown document type", field="type")
        if not doc.content or len(doc.content) > MAX_BYTES:
            raise ValidationFailedError("file must be 1 byte .. 25 MB", field="file")
        mime = doc.mime or mimetypes.guess_type(doc.filename)[0] or "application/octet-stream"
        name = _safe_name(doc.filename)
        async with self._sessions() as session, session.begin():
            if await session.get(Client, doc.client_id) is None:
                raise NotFoundError("client not found")
            row = Document(
                client_id=doc.client_id,
                type=doc.type,
                title=doc.title.strip()[:500],
                number=(doc.number or "").strip() or None,
                doc_date=doc.doc_date,
                filename=name,
                mime=mime,
                size_bytes=len(doc.content),
                uploaded_by=who.user_id,
                is_visible_to_client=doc.visible,
            )
            session.add(row)
            await session.flush()
            row.storage_key = f"clients/{doc.client_id}/{row.id}/{name}"
            await self._storage.put(self._bucket, row.storage_key, doc.content, mime)
            await audit.record(
                session,
                who.actor,
                "document.upload",
                "document",
                row.id,
                after={"client_id": doc.client_id, "type": doc.type, "title": doc.title},
            )
            document_id = row.id
        await self._enqueue(document_id)
        return document_id

    async def extract_text(self, document_id: int) -> str:
        """Текст документа для поиска бота; ошибка конвертации не роняет выдачу файла."""
        async with self._sessions() as session:
            row = await session.get(Document, document_id)
            if row is None or row.storage_key is None:
                return "skipped"
            key, filename, mime = row.storage_key, row.filename, row.mime
        try:
            content = await self._storage.get(self._bucket, key)
            text = (await self._converter.convert(filename, content, mime)).export_to_markdown()
            status, value = "done", text[:TEXT_LIMIT]
        except Exception:
            logger.exception("document_extract_failed", document_id=document_id)
            status, value = "failed", None
        async with self._sessions() as session, session.begin():
            row = await session.get(Document, document_id, with_for_update=True)
            if row is not None:
                row.extract_status, row.extracted_text = status, value
        return status

    async def download(self, who: Principal, document_id: int) -> tuple[bytes, str, str]:
        """Файл для сотрудника (CRM) через API — с записью в журнал доступа."""
        async with self._sessions() as session, session.begin():
            row = await session.get(Document, document_id)
            if row is None or row.storage_key is None:
                raise NotFoundError("document not found")
            await repo.log_access(session, document_id, "user", who.user_id)
            key, filename, mime = row.storage_key, row.filename, row.mime
        return await self._storage.get(self._bucket, key), filename, mime


def _safe_name(filename: str) -> str:
    name = PurePath(filename).name
    return "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in name)[:200] or "file"
