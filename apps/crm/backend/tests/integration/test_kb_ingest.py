"""Ингест: S3 → конвертер → чанки → embeddings → БД (фейковые внешние сервисы)."""

import pytest
from docling_core.types.doc import DoclingDocument
from docling_core.types.doc.labels import DocItemLabel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.kb import KbChunk, KbDocument
from app.services.kb.ingest import KbIngestService, NewKbFile
from app.services.kb.markdown_convert import MarkdownConverter
from tests.fakes import FakeEmbedder


class MemoryStorage:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}

    async def put(self, bucket: str, key: str, data: bytes, content_type: str) -> None:
        self.objects[(bucket, key)] = data

    async def get(self, bucket: str, key: str) -> bytes:
        return self.objects[(bucket, key)]


class FakeConverter:
    def __init__(self, fail: bool = False) -> None:
        self.calls = 0
        self.fail = fail

    async def convert(self, filename: str, content: bytes, mime: str) -> DoclingDocument:
        self.calls += 1
        if self.fail:
            raise RuntimeError("docling is down")
        doc = DoclingDocument(name=filename)
        doc.add_heading("Документ", level=1)
        doc.add_text(label=DocItemLabel.TEXT, text=content.decode())
        return doc


def make_service(
    sessions: async_sessionmaker[AsyncSession], converter: FakeConverter
) -> KbIngestService:
    return KbIngestService(sessions, MemoryStorage(), converter, FakeEmbedder(), "kb-sources")


async def chunk_count(sessions: async_sessionmaker[AsyncSession], document_id: int) -> int:
    async with sessions() as session:
        stmt = select(func.count()).select_from(KbChunk).where(KbChunk.document_id == document_id)
        return int((await session.execute(stmt)).scalar_one())


async def test_ingest_and_idempotency(sessions: async_sessionmaker[AsyncSession]) -> None:
    converter = FakeConverter()
    service = make_service(sessions, converter)
    file = NewKbFile(
        title="Тарифы", filename="tariffs.md", content=b"Tarif Start " * 300, language="ru"
    )
    document_id = await service.register_file(file)

    chunks = await service.ingest(document_id)
    assert chunks >= 1
    assert await chunk_count(sessions, document_id) == chunks
    assert await service.ingest(document_id) == chunks
    assert converter.calls == 1
    assert await service.ingest(document_id, force=True) == chunks
    assert converter.calls == 2
    async with sessions() as session:
        document = await session.get(KbDocument, document_id)
        assert document is not None
        assert (document.ingest_status, document.indexed_version) == ("done", 1)


async def test_failure_marks_document(sessions: async_sessionmaker[AsyncSession]) -> None:
    service = make_service(sessions, FakeConverter(fail=True))
    document_id = await service.register_file(
        NewKbFile(title="X", filename="x.pdf", content=b"x", language="ru")
    )
    with pytest.raises(RuntimeError, match="docling is down"):
        await service.ingest(document_id)
    async with sessions() as session:
        document = await session.get(KbDocument, document_id)
        assert document is not None
        assert document.ingest_status == "failed"
        assert "docling is down" in (document.ingest_error or "")


async def test_markdown_is_indexed_by_builtin_converter(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    service = KbIngestService(
        sessions, MemoryStorage(), MarkdownConverter(), FakeEmbedder(), "kb-sources"
    )
    text = (
        "---\ntitle: Доставка\nlanguage: ru\nsource: s\nupdated: 2026-10-21\n---\n"
        "# Доставка\n\nСрок 3 дня.\n\n| Город | Дней |\n|---|---|\n| Ташкент | 1 |\n"
    )
    document_id = await service.register_file(
        NewKbFile(title="Доставка", filename="delivery.md", content=text.encode(), language="ru")
    )
    assert await service.ingest(document_id) == 1
    async with sessions() as session:
        chunk = (
            await session.scalars(select(KbChunk).where(KbChunk.document_id == document_id))
        ).one()
        assert chunk.heading_path == "Доставка"
        assert "Ташкент" in chunk.content
        assert "language:" not in chunk.content  # front matter в чанки не попадает


async def test_legacy_non_markdown_document_fails_clearly(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    service = KbIngestService(
        sessions, MemoryStorage(), MarkdownConverter(), FakeEmbedder(), "kb-sources"
    )
    pdf_id = await service.register_file(
        NewKbFile(title="PDF", filename="a.pdf", content=b"%PDF", language="ru")
    )
    with pytest.raises(ValueError, match="only Markdown"):
        await service.ingest(pdf_id)
    async with sessions() as session:
        document = await session.get(KbDocument, pdf_id)
        assert document is not None
        assert document.ingest_status == "failed"
