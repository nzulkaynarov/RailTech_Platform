"""Квалификация, эскалации, журнал стадий (SPEC §5.4)."""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy import text as sql
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin
from app.models.leads import STAGES


class QualifierRun(TimestampMixin, Base):
    __tablename__ = "qualifier_runs"
    __table_args__ = (Index("ix_qualifier_runs_lead_id_id", "lead_id", "id"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"))
    trigger_message_id: Mapped[int | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL")
    )
    output: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    proposed_stage: Mapped[str | None] = mapped_column(String(16))
    applied_stage: Mapped[str | None] = mapped_column(String(16))
    rejected_reason: Mapped[str | None] = mapped_column(Text)
    triggers_fired: Mapped[list[str]] = mapped_column(ARRAY(String(32)), server_default=sql("'{}'"))
    score_before: Mapped[int] = mapped_column(Integer)
    score_after: Mapped[int] = mapped_column(Integer)
    escalated: Mapped[bool] = mapped_column(Boolean, server_default=sql("false"))
    error: Mapped[str | None] = mapped_column(Text)
    trace_id: Mapped[str | None] = mapped_column(String(64))
    model: Mapped[str | None] = mapped_column(String(128))
    cost_usd: Mapped[float | None] = mapped_column(Float)


class Escalation(TimestampMixin, Base):
    __tablename__ = "escalations"
    __table_args__ = (
        CheckConstraint("priority IN ('hot', 'warm', 'info')", name="priority"),
        CheckConstraint(
            "status IN ('open', 'taken', 'snoozed', 'returned', 'closed')", name="status"
        ),
        Index("ix_escalations_status_priority", "status", "priority"),
        Index(
            "uq_escalations_one_open_per_lead",
            "lead_id",
            unique=True,
            postgresql_where=sql("status IN ('open', 'snoozed')"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"))
    reason_codes: Mapped[list[str]] = mapped_column(ARRAY(String(32)))
    reason_text: Mapped[str | None] = mapped_column(Text)
    recommendation: Mapped[str | None] = mapped_column(Text)
    priority: Mapped[str] = mapped_column(String(8))
    status: Mapped[str] = mapped_column(String(16), server_default=sql("'open'"))
    taken_by_user_id: Mapped[int | None] = mapped_column(BigInteger)
    taken_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    channel_message_id: Mapped[int | None] = mapped_column(BigInteger)
    sla_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sla_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    snoozed_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    outcome: Mapped[str | None] = mapped_column(String(32))


class StageTransition(TimestampMixin, Base):
    __tablename__ = "stage_transitions"
    __table_args__ = (
        CheckConstraint(f"from_stage IN ({STAGES})", name="from_stage"),
        CheckConstraint(f"to_stage IN ({STAGES})", name="to_stage"),
        CheckConstraint(
            "source IN ('qualifier', 'trigger', 'user', 'timer', 'system')", name="source"
        ),
        Index("ix_stage_transitions_lead_id_id", "lead_id", "id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"))
    from_stage: Mapped[str] = mapped_column(String(16))
    to_stage: Mapped[str] = mapped_column(String(16))
    source: Mapped[str] = mapped_column(String(16))
    actor_user_id: Mapped[int | None] = mapped_column(BigInteger)
    reason: Mapped[str] = mapped_column(Text)
