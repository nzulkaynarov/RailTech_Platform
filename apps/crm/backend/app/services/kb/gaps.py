"""Регистрация пробелов базы знаний (SPEC §7.1 fallback, сценарий C4)."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.language import Language
from app.domain.text import normalize_question
from app.repositories import kb as repo


async def register_gap(
    session: AsyncSession,
    *,
    question: str,
    language: Language,
    best_score: float | None,
    lead_id: int | None,
) -> int | None:
    """id пробела; None, если вопрос пуст после нормализации."""
    normalized = normalize_question(question)
    if not normalized:
        return None
    return await repo.upsert_gap(
        session,
        question=question.strip()[:2000],
        normalized=normalized[:2000],
        language=language,
        best_score=best_score,
        lead_id=lead_id,
    )
