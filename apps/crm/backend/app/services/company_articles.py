"""Статьи компании (W18A-P5, B-079): создать, править, опубликовать, снять, удалить.

Правят администраторы (право `company_articles:write`), черновики видят и те, кто читает раздел
(`company_articles:read`, директор); опубликованные читает любой сотрудник. Каждая мутация пишет
строку журнала действий в той же транзакции; текст статьи в журнал не попадает — только заголовок,
язык, статус и длина.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain import company_articles as rules
from app.domain.errors import NotFoundError, Reason, ValidationFailedError
from app.models.auth import User
from app.models.company_articles import CompanyArticle
from app.security import audit
from app.security.audit import Actor

# Предохранитель: «Помощь» отдаёт опубликованные статьи целиком одним ответом.
PUBLISHED_LIMIT = 500


@dataclass(frozen=True, slots=True)
class ArticleView:
    id: int
    title: str
    body: str
    language: str
    status: str
    created_by_name: str | None
    updated_by_name: str | None
    created_at: datetime
    updated_at: datetime
    published_at: datetime | None


def _utcnow() -> datetime:
    return datetime.now(UTC)


def invalid(exc: rules.ArticleValueError) -> ValidationFailedError:
    """Ошибка значения -> 422 с `details.field` и `details.reason`."""
    return ValidationFailedError(str(exc), reason=Reason(exc.reason), field=exc.field)


def _snapshot(article: CompanyArticle) -> dict[str, Any]:
    return {
        "title": article.title,
        "language": article.language,
        "status": article.status,
        "body_length": len(article.body),
    }


class CompanyArticleService:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._sessions = sessions
        self._clock = clock

    # --- читатели -------------------------------------------------------------------------------

    async def list_published(self) -> list[ArticleView]:
        """Опубликованные статьи — любому сотруднику; новые выше."""
        async with self._sessions() as session:
            rows = (
                await session.scalars(
                    select(CompanyArticle)
                    .where(CompanyArticle.status == "published")
                    .order_by(CompanyArticle.published_at.desc(), CompanyArticle.id.desc())
                    .limit(PUBLISHED_LIMIT)
                )
            ).all()
            return await self._views(session, rows)

    async def list_all(self, *, status: str | None = None) -> list[ArticleView]:
        """Все статьи, включая черновики, — тем, кто читает раздел «Статьи компании»."""
        try:
            if status is not None:
                rules.checked_status(status)
        except rules.ArticleValueError as exc:
            raise invalid(exc) from exc
        stmt = select(CompanyArticle)
        if status is not None:
            stmt = stmt.where(CompanyArticle.status == status)
        async with self._sessions() as session:
            rows = (
                await session.scalars(
                    stmt.order_by(CompanyArticle.updated_at.desc(), CompanyArticle.id.desc())
                )
            ).all()
            return await self._views(session, rows)

    async def get(self, article_id: int) -> ArticleView:
        async with self._sessions() as session:
            article = await session.get(CompanyArticle, article_id)
            if article is None:
                raise NotFoundError("article not found")
            return (await self._views(session, [article]))[0]

    # --- администратор --------------------------------------------------------------------------

    async def create(
        self, actor: Actor, *, title: str, body: str, language: str = "ru"
    ) -> ArticleView:
        try:
            title_ok = rules.checked_title(title)
            body_ok = rules.checked_body(body)
            language_ok = rules.checked_language(language)
        except rules.ArticleValueError as exc:
            raise invalid(exc) from exc
        now = self._clock()
        async with self._sessions() as session, session.begin():
            article = CompanyArticle(
                title=title_ok,
                body=body_ok,
                language=language_ok,
                status="draft",
                created_by_id=actor.user_id,
                updated_by_id=actor.user_id,
                created_at=now,
                updated_at=now,
            )
            session.add(article)
            await session.flush()
            await audit.record(
                session, actor, "company_article.create", "company_article", article.id,
                after=_snapshot(article),
            )  # fmt: skip
            article_id = article.id
        return await self.get(article_id)

    async def update(
        self,
        actor: Actor,
        article_id: int,
        *,
        title: str | None = None,
        body: str | None = None,
        language: str | None = None,
    ) -> ArticleView:
        try:
            title_ok = rules.checked_title(title) if title is not None else None
            body_ok = rules.checked_body(body) if body is not None else None
            language_ok = rules.checked_language(language) if language is not None else None
        except rules.ArticleValueError as exc:
            raise invalid(exc) from exc
        now = self._clock()
        async with self._sessions() as session, session.begin():
            article = await self._locked(session, article_id)
            before = _snapshot(article)
            if title_ok is not None:
                article.title = title_ok
            if body_ok is not None:
                article.body = body_ok
            if language_ok is not None:
                article.language = language_ok
            article.updated_at = now
            article.updated_by_id = actor.user_id
            await audit.record(
                session, actor, "company_article.update", "company_article", article_id,
                before=before, after=_snapshot(article),
            )  # fmt: skip
        return await self.get(article_id)

    async def publish(self, actor: Actor, article_id: int) -> ArticleView:
        return await self._set_status(actor, article_id, "published")

    async def unpublish(self, actor: Actor, article_id: int) -> ArticleView:
        return await self._set_status(actor, article_id, "draft")

    async def delete(self, actor: Actor, article_id: int) -> None:
        async with self._sessions() as session, session.begin():
            article = await self._locked(session, article_id)
            await audit.record(
                session, actor, "company_article.delete", "company_article", article_id,
                before=_snapshot(article),
            )  # fmt: skip
            await session.delete(article)

    # --- внутреннее -----------------------------------------------------------------------------

    async def _set_status(self, actor: Actor, article_id: int, status: str) -> ArticleView:
        now = self._clock()
        async with self._sessions() as session, session.begin():
            article = await self._locked(session, article_id)
            before = _snapshot(article)
            if article.status != status:
                article.status = status
                article.updated_at = now
                article.updated_by_id = actor.user_id
                article.published_at = now if status == "published" else None
                action = (
                    "company_article.publish"
                    if status == "published"
                    else "company_article.unpublish"
                )
                await audit.record(
                    session, actor, action, "company_article", article_id,
                    before=before, after=_snapshot(article),
                )  # fmt: skip
        return await self.get(article_id)

    @staticmethod
    async def _locked(session: AsyncSession, article_id: int) -> CompanyArticle:
        article = await session.get(CompanyArticle, article_id, with_for_update=True)
        if article is None:
            raise NotFoundError("article not found")
        return article

    @staticmethod
    async def _views(
        session: AsyncSession, articles: Sequence[CompanyArticle]
    ) -> list[ArticleView]:
        user_ids = {
            uid for a in articles for uid in (a.created_by_id, a.updated_by_id) if uid is not None
        }
        names: dict[int, str] = {}
        if user_ids:
            found = await session.execute(
                select(User.id, User.full_name).where(User.id.in_(user_ids))
            )
            names = dict(found.all())
        return [
            ArticleView(
                id=a.id,
                title=a.title,
                body=a.body,
                language=a.language,
                status=a.status,
                created_by_name=names.get(a.created_by_id) if a.created_by_id else None,
                updated_by_name=names.get(a.updated_by_id) if a.updated_by_id else None,
                created_at=a.created_at,
                updated_at=a.updated_at,
                published_at=a.published_at,
            )
            for a in articles
        ]


__all__: Sequence[str] = ("PUBLISHED_LIMIT", "ArticleView", "CompanyArticleService")
