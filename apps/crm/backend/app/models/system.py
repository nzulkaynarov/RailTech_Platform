"""Служебные таблицы эксплуатации (SPEC §13): дедупликация системных алертов."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, Text, func
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
