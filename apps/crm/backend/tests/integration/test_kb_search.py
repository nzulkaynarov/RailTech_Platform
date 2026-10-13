"""Гибридный поиск на реальном Postgres: вектор + BM25 + RRF + фильтры (ADR-0007)."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.kb import KbGap
from app.services.kb.gaps import register_gap
from app.services.kb.search import KbSearchService
from tests.fakes import FakeEmbedder
from tests.integration.kb_seed import seed_kb


async def test_finds_relevant_chunk_first(sessions: async_sessionmaker[AsyncSession]) -> None:
    await seed_kb(sessions)
    result = await KbSearchService(sessions, FakeEmbedder()).search("Подключается ли касса к 1С?")
    assert result.hits[0].document_title == "Кассы RT-POS"
    assert result.best_score is not None
    assert result.language == "ru"


async def test_russian_stemming_matches_word_forms(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    await seed_kb(sessions)
    result = await KbSearchService(sessions, FakeEmbedder()).search("мониторингом вагона")
    assert result.hits[0].document_title == "Логистика RT-Track"


async def test_product_filter(sessions: async_sessionmaker[AsyncSession]) -> None:
    await seed_kb(sessions)
    service = KbSearchService(sessions, FakeEmbedder())
    result = await service.search("касса тариф", product_key="logistics")
    assert result.hits
    assert {h.product_key for h in result.hits} == {"logistics"}


async def test_uzbek_query(sessions: async_sessionmaker[AsyncSession]) -> None:
    await seed_kb(sessions)
    result = await KbSearchService(sessions, FakeEmbedder()).search("vagonlarni kuzatish")
    assert result.language == "uz"
    assert result.hits[0].document_title == "RT-Track xizmati"


async def test_inactive_documents_are_hidden(sessions: async_sessionmaker[AsyncSession]) -> None:
    ids = await seed_kb(sessions)
    async with sessions() as session, session.begin():
        from app.models.kb import KbDocument

        document = await session.get(KbDocument, ids["Кассы RT-POS"])
        assert document is not None
        document.is_active = False
    result = await KbSearchService(sessions, FakeEmbedder()).search("касса 1С")
    assert all(h.document_title != "Кассы RT-POS" for h in result.hits)


async def test_top_k_limits_results(sessions: async_sessionmaker[AsyncSession]) -> None:
    await seed_kb(sessions)
    result = await KbSearchService(sessions, FakeEmbedder()).search("касса вагон", top_k=2)
    assert len(result.hits) <= 2


async def test_gap_upsert_counts_occurrences(sessions: async_sessionmaker[AsyncSession]) -> None:
    async with sessions() as session, session.begin():
        first = await register_gap(
            session,
            question="Есть ли доставка в Нукус?",
            language="ru",
            best_score=0.2,
            lead_id=None,
        )
        second = await register_gap(
            session,
            question="  есть ли ДОСТАВКА в нукус ",
            language="ru",
            best_score=0.3,
            lead_id=None,
        )
        assert first == second
        gap = (await session.scalars(select(KbGap))).one()
    assert gap.occurrences == 2
    assert gap.best_score == 0.3
