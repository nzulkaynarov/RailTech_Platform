"""Статьи компании — схемы `CompanyArticle*` контракта BFF (W18A-P5, B-079).

Владелец данных — CRM (ADR-0015). BFF отдаёт статью в словаре Платформы; текст не обрабатывает:
безопасный показ Markdown (без HTML и скриптов) — забота рендера в SPA, длину проверяет CRM.
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

CompanyArticleLanguage = Literal["ru", "uz", "en"]
CompanyArticleStatus = Literal["draft", "published"]


class CompanyArticleCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=1000)
    body: str = Field(min_length=1, max_length=100000)
    language: CompanyArticleLanguage = "ru"


class CompanyArticleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=1000)
    body: str | None = Field(default=None, min_length=1, max_length=100000)
    language: CompanyArticleLanguage | None = None


class CompanyArticle(BaseModel):
    id: int = Field(ge=1)
    title: str
    body: str
    language: CompanyArticleLanguage
    status: CompanyArticleStatus
    created_by_name: str | None = None
    updated_by_name: str | None = None
    created_at: datetime
    updated_at: datetime
    published_at: datetime | None = None


class CompanyArticleList(BaseModel):
    items: list[CompanyArticle]


def to_article(row: dict[str, Any]) -> CompanyArticle:
    return CompanyArticle(
        id=int(row["id"]),
        title=str(row["title"]),
        body=str(row["body"]),
        language=row["language"],
        status=row["status"],
        created_by_name=row.get("created_by_name") or None,
        updated_by_name=row.get("updated_by_name") or None,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        published_at=row.get("published_at") or None,
    )
