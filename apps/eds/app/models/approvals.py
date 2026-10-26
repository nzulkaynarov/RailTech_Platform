"""Маршруты согласования (runbook волны 12 §2.5): маршрут = круг, шаги — «кто решает»."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ApprovalRoute(Base):
    """Один круг согласования документа EDS или КП ERP. Возврат закрывает маршрут; отправка открывает новый круг.

    Коммерческого содержания КП маршрут не знает: `quote_snapshot` — снимок `quote.ready_for_approval` для показа.
    """

    __tablename__ = "approval_routes"
    __table_args__ = (
        CheckConstraint("template IN ('memo', 'application', 'report', 'quote')", name="template"),
        CheckConstraint("status IN ('open', 'approved', 'returned', 'rejected')", name="status"),
        UniqueConstraint("document_id", "round", name="uq_approval_routes_document_round"),
        UniqueConstraint("erp_quote_id", "quote_version", name="uq_approval_routes_quote_version"),
        Index("ix_approval_routes_created_at_id", "created_at", "id"),
        Index("ix_approval_routes_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    template: Mapped[str] = mapped_column(String(16))
    title: Mapped[str] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(16))
    round: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    current_step: Mapped[int | None] = mapped_column(Integer)
    document_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("documents.id", ondelete="CASCADE"))
    erp_quote_id: Mapped[int | None] = mapped_column(BigInteger)
    quote_number: Mapped[str | None] = mapped_column(String(64))
    quote_version: Mapped[int | None] = mapped_column(Integer)
    erp_deal_id: Mapped[int | None] = mapped_column(BigInteger)
    deal_number: Mapped[str | None] = mapped_column(String(64))
    crm_client_id: Mapped[int | None] = mapped_column(BigInteger)
    erp_company_id: Mapped[int | None] = mapped_column(BigInteger)
    eds_letter_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    quote_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    outgoing_number: Mapped[str | None] = mapped_column(String(32))
    channels: Mapped[list[str] | None] = mapped_column(JSONB)
    # КП одобрено, хотя готово позже срока резолюции: строка `due` чек-листа — предупреждение (C1-G-1, 2026-10-26)
    approved_late: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ApprovalStep(Base):
    """Шаг маршрута: сотрудник (`assignee_crm_user_id`) или любой с правом (`assignee_permission`) — ровно одно."""

    __tablename__ = "approval_steps"
    __table_args__ = (
        CheckConstraint("(assignee_crm_user_id IS NULL) <> (assignee_permission IS NULL)", name="one_assignee"),
        CheckConstraint(
            "status IN ('pending', 'current', 'approved', 'returned', 'rejected', 'skipped')", name="status"
        ),
        ForeignKeyConstraint(
            ["approval_id"],
            ["approval_routes.id"],
            name="fk_approval_steps_approval_id_approval_routes",
            ondelete="CASCADE",
        ),
        Index("ix_approval_steps_assignee", "assignee_crm_user_id"),
    )

    approval_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    index: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    label: Mapped[str] = mapped_column(String(64))
    assignee_crm_user_id: Mapped[int | None] = mapped_column(BigInteger)
    assignee_permission: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16))
    decided_by: Mapped[int | None] = mapped_column(BigInteger)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    comment: Mapped[str | None] = mapped_column(Text)
