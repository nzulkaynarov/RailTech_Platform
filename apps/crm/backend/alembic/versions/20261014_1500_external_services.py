"""external_services: проверки, инциденты и выключатели внешних сервисов (M3-CRM-12, ADR-0024)

Revision ID: 0022_external_services
Revises: 0021_email_log
Create Date: 2026-10-14 15:00:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0022_external_services"
down_revision: str | None = "0021_email_log"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STATUS = "status IN ('ok', 'warn', 'fail', 'unknown', 'off')"


def upgrade() -> None:
    op.create_table(
        "external_service_checks",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("service_key", sa.String(length=64), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tier", sa.String(length=8), nullable=False),
        sa.Column("status", sa.String(length=8), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("hint", sa.Text(), nullable=True),
        sa.Column(
            "metrics",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.CheckConstraint(_STATUS, name=op.f("ck_external_service_checks_status")),
        sa.CheckConstraint(
            "tier IN ('cheap', 'heavy', 'manual')", name=op.f("ck_external_service_checks_tier")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_external_service_checks")),
    )
    op.create_index(
        "ix_external_service_checks_service_at",
        "external_service_checks",
        ["service_key", "checked_at"],
    )
    op.create_index(
        "ix_external_service_checks_checked_at", "external_service_checks", ["checked_at"]
    )
    op.create_table(
        "external_service_incidents",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("service_key", sa.String(length=64), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("alerted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recovery_alerted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_external_service_incidents")),
    )
    op.create_index(
        "ix_external_service_incidents_service_started",
        "external_service_incidents",
        ["service_key", "started_at"],
    )
    op.create_index(
        "uq_external_service_incidents_open",
        "external_service_incidents",
        ["service_key"],
        unique=True,
        postgresql_where=sa.text("ended_at IS NULL"),
    )
    op.create_table(
        "external_service_switches",
        sa.Column("service_key", sa.String(length=64), nullable=False),
        sa.Column("disabled", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.String(length=200), nullable=True),
        sa.Column(
            "state",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("changed_by", sa.BigInteger(), nullable=True),
        sa.Column(
            "changed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["changed_by"],
            ["users.id"],
            name=op.f("fk_external_service_switches_changed_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("service_key", name=op.f("pk_external_service_switches")),
    )


def downgrade() -> None:
    op.drop_table("external_service_switches")
    op.drop_index("uq_external_service_incidents_open", table_name="external_service_incidents")
    op.drop_index(
        "ix_external_service_incidents_service_started", table_name="external_service_incidents"
    )
    op.drop_table("external_service_incidents")
    op.drop_index("ix_external_service_checks_checked_at", table_name="external_service_checks")
    op.drop_index("ix_external_service_checks_service_at", table_name="external_service_checks")
    op.drop_table("external_service_checks")
