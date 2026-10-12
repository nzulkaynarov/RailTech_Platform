"""Служебные таблицы эксплуатации (SPEC §13): дедупликация системных алертов."""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    Identity,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class SystemAlert(Base):
    """Состояние проверки монитора: активна ли, с какого момента и когда ушло в канал."""

    __tablename__ = "system_alerts"

    key: Mapped[str] = mapped_column(String(160), primary_key=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    detail: Mapped[str | None] = mapped_column(Text)
    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class LlmUsage(Base):
    """Единый учёт вызовов моделей (аудит 2026-10-12 §3 п. 5): каждый вызов — строка.

    `kind='test'` — прогоны eval/load-test (флаг окружения `LLM_USAGE_KIND`).
    """

    __tablename__ = "llm_usage"
    __table_args__ = (CheckConstraint("kind IN ('work', 'test')", name="kind"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    purpose: Mapped[str] = mapped_column(String(32), nullable=False)
    alias: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str | None] = mapped_column(String(32))
    model: Mapped[str | None] = mapped_column(String(128))
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    lead_id: Mapped[int | None] = mapped_column(BigInteger)
    kind: Mapped[str] = mapped_column(String(8), nullable=False, default="work")
