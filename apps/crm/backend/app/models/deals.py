"""Сделки клиента (SPEC §5.2, ADR-0019): продукт, сумма, стадия, причина итога."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CHAR,
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Numeric,
    String,
)
from sqlalchemy import text as sql
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Deal(TimestampMixin, Base):
    __tablename__ = "deals"
    __table_args__ = (
        CheckConstraint("stage IN ('open', 'won', 'lost')", name="stage"),
        CheckConstraint("amount IS NULL OR amount >= 0", name="amount"),
        Index("ix_deals_client_id", "client_id"),
        Index("ix_deals_lead_id", "lead_id"),
        Index("ix_deals_stage_closed_at", "stage", "closed_at"),
        # Одна заявка ERP — одно зеркало (FIX-33); NULL (локальные сделки) уникальность не нарушают.
        Index("uq_deals_erp_deal_id", "erp_deal_id", unique=True),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    client_id: Mapped[int | None] = mapped_column(ForeignKey("clients.id", ondelete="SET NULL"))
    lead_id: Mapped[int | None] = mapped_column(ForeignKey("leads.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(String(255))
    product_key: Mapped[str | None] = mapped_column(String(64))
    amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    currency: Mapped[str] = mapped_column(CHAR(3), server_default=sql("'UZS'"))
    stage: Mapped[str] = mapped_column(String(8), server_default=sql("'open'"))
    expected_close_date: Mapped[date | None] = mapped_column(Date)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lost_reason: Mapped[str | None] = mapped_column(String(120))
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    erp_deal_id: Mapped[int | None] = mapped_column(BigInteger)
    external_stage: Mapped[str | None] = mapped_column(String(64))
    # `occurred_at` последнего применённого события ERP: более старое событие стадию не откатывает.
    external_stage_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
