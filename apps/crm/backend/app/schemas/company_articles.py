"""DTO статей компании (W18A-P5, B-079)."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.domain.company_articles import Language, Status


class ArticleIn(BaseModel):
    """Новая статья. Значения проверяет домен (`details.reason`), здесь — грубые пределы."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(max_length=1000)
    body: str = Field(max_length=100000)
    language: str = Field(default="ru", max_length=8)


class ArticlePatch(BaseModel):
    """Правка: пришедшие поля меняются, остальные остаются. Статус меняют отдельные действия."""

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, max_length=1000)
    body: str | None = Field(default=None, max_length=100000)
    language: str | None = Field(default=None, max_length=8)


class ArticleOut(BaseModel):
    id: int
    title: str
    body: str
    language: Language
    status: Status
    created_by_name: str | None = None
    updated_by_name: str | None = None
    created_at: datetime
    updated_at: datetime
    published_at: datetime | None = None


class ArticleListOut(BaseModel):
    items: list[ArticleOut]
