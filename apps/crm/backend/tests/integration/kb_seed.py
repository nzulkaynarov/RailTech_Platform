"""Посев базы знаний для integration-тестов (фейковые векторы, без моделей)."""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.kb import KbDocument, Product
from app.repositories import kb as repo
from app.services.settings import SettingsService
from tests.fakes import FakeEmbedder

# Хэш-векторы FakeEmbedder дают сходство ~0.55–0.6 у верных ответов: порог по умолчанию
# (0.70, откалиброван на реальных эмбеддингах) для них слишком строг.
HASH_MIN_SCORE = 0.5

DOCS = [
    (
        "pos",
        "ru",
        "Кассы RT-POS",
        [
            ("Кассы RT-POS", "Онлайн-касса RT-POS подключается к 1С и печатает фискальные чеки."),
            ("Кассы RT-POS > Тарифы", "Тариф Старт: одна касса, облачный учёт товаров и отчёты."),
        ],
    ),
    (
        "logistics",
        "ru",
        "Логистика RT-Track",
        [
            ("RT-Track", "Мониторинг вагонов и контейнеров в реальном времени по GPS."),
        ],
    ),
    (
        "logistics",
        "uz",
        "RT-Track xizmati",
        [
            ("RT-Track", "Vagonlarni real vaqtda GPS orqali kuzatish xizmati."),
        ],
    ),
]


async def seed_kb(sessions: async_sessionmaker[AsyncSession]) -> dict[str, int]:
    embedder = FakeEmbedder()
    ids: dict[str, int] = {}
    async with sessions() as session, session.begin():
        session.add_all(
            [Product(key="pos", name="RT-POS"), Product(key="logistics", name="RT-Track")]
        )
        await session.flush()
        for product, language, title, chunks in DOCS:
            document = KbDocument(
                title=title,
                product_key=product,
                language=language,
                source_type="manual",
                ingest_status="pending",
            )
            session.add(document)
            await session.flush()
            vectors = await embedder.embed_documents([(f"{h}\n{c}", title) for h, c in chunks])
            await repo.replace_chunks(
                session,
                document,
                [
                    repo.NewChunk(
                        position=i, heading_path=h, content=c, token_count=len(c) // 4, embedding=v
                    )
                    for i, ((h, c), v) in enumerate(zip(chunks, vectors, strict=True))
                ],
            )
            ids[title] = document.id
    return ids


async def hash_threshold(sessions: async_sessionmaker[AsyncSession]) -> None:
    """Порог KB под фейковые векторы (см. HASH_MIN_SCORE)."""
    await SettingsService(sessions).update("kb", {"min_score": HASH_MIN_SCORE}, None)
