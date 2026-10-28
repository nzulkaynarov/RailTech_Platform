"""Статьи компании: внутренние инструкции, которые админ пишет в Настройках (W18A-P5, B-079)."""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

ARTICLE_LANGUAGES = ("ru", "uz", "en")
ARTICLE_STATUSES = ("draft", "published")


class CompanyArticle(Base):
    """Статья компании: заголовок, Markdown, язык (ru/uz/en), «Черновик» или «Опубликовано»."""

    __tablename__ = "company_articles"
    __table_args__ = (
        CheckConstraint("language IN ('ru', 'uz', 'en')", name="language"),
        CheckConstraint("status IN ('draft', 'published')", name="status"),
        Index("ix_company_articles_status", "status", "updated_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    language: Mapped[str] = mapped_column(String(2), server_default="ru")
    status: Mapped[str] = mapped_column(String(12), server_default="draft")
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    updated_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
