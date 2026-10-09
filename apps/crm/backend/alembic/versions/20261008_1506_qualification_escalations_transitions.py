"""qualifier_runs, escalations, stage_transitions (Фаза 3)

Revision ID: 0004_qualification
Revises: 0003_leads
Create Date: 2026-10-08 15:06:20.298198+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_qualification"
down_revision: str | Sequence[str] | None = "0003_leads"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UPDATED_AT_TABLES = ("qualifier_runs", "escalations", "stage_transitions")


def upgrade() -> None:
    op.create_table(
        "escalations",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("lead_id", sa.BigInteger(), nullable=False),
        sa.Column("reason_codes", postgresql.ARRAY(sa.String(length=32)), nullable=False),
        sa.Column("reason_text", sa.Text(), nullable=True),
        sa.Column("recommendation", sa.Text(), nullable=True),
        sa.Column("priority", sa.String(length=8), nullable=False),
        sa.Column("status", sa.String(length=16), server_default=sa.text("'open'"), nullable=False),
        sa.Column("taken_by_user_id", sa.BigInteger(), nullable=True),
        sa.Column("taken_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("channel_message_id", sa.BigInteger(), nullable=True),
        sa.Column("sla_due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sla_notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("snoozed_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("outcome", sa.String(length=32), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "priority IN ('hot', 'warm', 'info')", name=op.f("ck_escalations_priority")
        ),
        sa.CheckConstraint(
            "status IN ('open', 'taken', 'snoozed', 'returned', 'closed')",
            name=op.f("ck_escalations_status"),
        ),
        sa.ForeignKeyConstraint(
            ["lead_id"], ["leads.id"], name=op.f("fk_escalations_lead_id_leads"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_escalations")),
    )
    op.create_index(
        "ix_escalations_status_priority", "escalations", ["status", "priority"], unique=False
    )
    op.create_index(
        "uq_escalations_one_open_per_lead",
        "escalations",
        ["lead_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('open', 'snoozed')"),
    )
    op.create_table(
        "stage_transitions",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("lead_id", sa.BigInteger(), nullable=False),
        sa.Column("from_stage", sa.String(length=16), nullable=False),
        sa.Column("to_stage", sa.String(length=16), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("actor_user_id", sa.BigInteger(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "from_stage IN ('new','engaged','qualified','handoff','in_progress',"
            "'won','customer','lost','unresponsive')",
            name=op.f("ck_stage_transitions_from_stage"),
        ),
        sa.CheckConstraint(
            "source IN ('qualifier', 'trigger', 'user', 'timer', 'system')",
            name=op.f("ck_stage_transitions_source"),
        ),
        sa.CheckConstraint(
            "to_stage IN ('new','engaged','qualified','handoff','in_progress',"
            "'won','customer','lost','unresponsive')",
            name=op.f("ck_stage_transitions_to_stage"),
        ),
        sa.ForeignKeyConstraint(
            ["lead_id"],
            ["leads.id"],
            name=op.f("fk_stage_transitions_lead_id_leads"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_stage_transitions")),
    )
    op.create_index(
        "ix_stage_transitions_lead_id_id", "stage_transitions", ["lead_id", "id"], unique=False
    )
    op.create_table(
        "qualifier_runs",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("lead_id", sa.BigInteger(), nullable=False),
        sa.Column("trigger_message_id", sa.BigInteger(), nullable=True),
        sa.Column("output", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("proposed_stage", sa.String(length=16), nullable=True),
        sa.Column("applied_stage", sa.String(length=16), nullable=True),
        sa.Column("rejected_reason", sa.Text(), nullable=True),
        sa.Column(
            "triggers_fired",
            postgresql.ARRAY(sa.String(length=32)),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("score_before", sa.Integer(), nullable=False),
        sa.Column("score_after", sa.Integer(), nullable=False),
        sa.Column("escalated", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("trace_id", sa.String(length=64), nullable=True),
        sa.Column("model", sa.String(length=128), nullable=True),
        sa.Column("cost_usd", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["lead_id"],
            ["leads.id"],
            name=op.f("fk_qualifier_runs_lead_id_leads"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["trigger_message_id"],
            ["messages.id"],
            name=op.f("fk_qualifier_runs_trigger_message_id_messages"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_qualifier_runs")),
    )
    op.create_index(
        "ix_qualifier_runs_lead_id_id", "qualifier_runs", ["lead_id", "id"], unique=False
    )
    for table in UPDATED_AT_TABLES:
        op.execute(
            f"CREATE TRIGGER trg_{table}_updated_at BEFORE UPDATE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
        )


def downgrade() -> None:
    op.drop_index("ix_qualifier_runs_lead_id_id", table_name="qualifier_runs")
    op.drop_table("qualifier_runs")
    op.drop_index("ix_stage_transitions_lead_id_id", table_name="stage_transitions")
    op.drop_table("stage_transitions")
    op.drop_index(
        "uq_escalations_one_open_per_lead",
        table_name="escalations",
        postgresql_where=sa.text("status IN ('open', 'snoozed')"),
    )
    op.drop_index("ix_escalations_status_priority", table_name="escalations")
    op.drop_table("escalations")
