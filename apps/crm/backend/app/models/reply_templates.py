"""Шаблоны быстрых ответов менеджера (аудит 2026-10-12 §5): название и текст на ru/uz/en."""

from typing import Any

from sqlalchemy import BigInteger, ForeignKey, Identity, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class ReplyTemplate(TimestampMixin, Base):
    __tablename__ = "reply_templates"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    # {"ru": ..., "uz": ..., "en": ...}; подстановки {name}, {manager} — заполняет CRM.
    text: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
