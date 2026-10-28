"""Статьи компании (W18A-P5, B-079, ADR-0015): внутренние инструкции в Настройках и в «Помощи».

Опубликованные читает любой сотрудник (`/me/company-articles`); все статьи с черновиками — права
`company_articles:read` раздела `admin` каталога (директор читает), создание, правка, публикация и
удаление — `company_articles:write` (администратор).
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, status

from app.api.deps import ContainerDep, require
from app.api.v1.me import Settled
from app.schemas.company_articles import (
    ArticleIn,
    ArticleListOut,
    ArticleOut,
    ArticlePatch,
)
from app.security.principal import Principal
from app.services.company_articles import ArticleView

router = APIRouter(prefix="/api/v1/company-articles", tags=["company-articles"])
# Опубликованные — отдельный префикс: читатель не должен упираться в права раздела `admin`.
mine_router = APIRouter(prefix="/api/v1/me/company-articles", tags=["company-articles"])

Reader = Annotated[Principal, Depends(require("company_articles", "read"))]
Writer = Annotated[Principal, Depends(require("company_articles", "write"))]
ArticleId = Annotated[int, Path(gt=0)]


def _out(view: ArticleView) -> ArticleOut:
    return ArticleOut(
        id=view.id,
        title=view.title,
        body=view.body,
        language=view.language,
        status=view.status,
        created_by_name=view.created_by_name,
        updated_by_name=view.updated_by_name,
        created_at=view.created_at,
        updated_at=view.updated_at,
        published_at=view.published_at,
    )


@mine_router.get("", response_model=ArticleListOut)
async def list_published_articles(_: Settled, container: ContainerDep) -> ArticleListOut:
    """Опубликованные статьи компании для «Помощи»; черновиков здесь нет ни у кого."""
    items = await container.company_articles.list_published()
    return ArticleListOut(items=[_out(v) for v in items])


@router.get("", response_model=ArticleListOut)
async def list_articles(
    _: Reader,
    container: ContainerDep,
    status_: Annotated[str | None, Query(alias="status", max_length=16)] = None,
) -> ArticleListOut:
    items = await container.company_articles.list_all(status=status_)
    return ArticleListOut(items=[_out(v) for v in items])


@router.get("/{article_id}", response_model=ArticleOut)
async def get_article(article_id: ArticleId, _: Reader, container: ContainerDep) -> ArticleOut:
    return _out(await container.company_articles.get(article_id))


@router.post("", response_model=ArticleOut, status_code=status.HTTP_201_CREATED)
async def create_article(body: ArticleIn, who: Writer, container: ContainerDep) -> ArticleOut:
    """Новая статья всегда черновик: опубликовать — отдельное действие."""
    view = await container.company_articles.create(
        who.actor, title=body.title, body=body.body, language=body.language
    )
    return _out(view)


@router.patch("/{article_id}", response_model=ArticleOut)
async def update_article(
    article_id: ArticleId, body: ArticlePatch, who: Writer, container: ContainerDep
) -> ArticleOut:
    view = await container.company_articles.update(
        who.actor, article_id, title=body.title, body=body.body, language=body.language
    )
    return _out(view)


@router.post("/{article_id}/publish", response_model=ArticleOut)
async def publish_article(
    article_id: ArticleId, who: Writer, container: ContainerDep
) -> ArticleOut:
    return _out(await container.company_articles.publish(who.actor, article_id))


@router.post("/{article_id}/unpublish", response_model=ArticleOut)
async def unpublish_article(
    article_id: ArticleId, who: Writer, container: ContainerDep
) -> ArticleOut:
    """Вернуть опубликованную статью в черновики: из «Помощи» она исчезает."""
    return _out(await container.company_articles.unpublish(who.actor, article_id))


@router.delete("/{article_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_article(article_id: ArticleId, who: Writer, container: ContainerDep) -> None:
    await container.company_articles.delete(who.actor, article_id)
