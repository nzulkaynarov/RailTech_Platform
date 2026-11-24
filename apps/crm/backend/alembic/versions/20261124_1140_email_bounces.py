"""Delivery reports: message_id and bounce facts in email_log, table email_undeliverable.

One additive migration: nullable columns and a new table. Downgrade drops them.

Revision ID: 51e8c6eed04d
Revises: 5a8e2c1f7b30
Create Date: 2026-11-24 11:40:38.247215+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "51e8c6eed04d"
down_revision: str | Sequence[str] | None = "5a8e2c1f7b30"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("email_log", sa.Column("message_id", sa.String(255), nullable=True))
    op.add_column("email_log", sa.Column("bounced_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("email_log", sa.Column("bounce_status", sa.String(16), nullable=True))
    op.add_column("email_log", sa.Column("bounce_reason", sa.String(32), nullable=True))
    op.add_column("email_log", sa.Column("bounce_message_id", sa.String(255), nullable=True))
    op.create_index(
        "ix_email_log_message_id",
        "email_log",
        ["message_id"],
        postgresql_where=sa.text("message_id IS NOT NULL"),
    )
    op.create_table(
        "email_undeliverable",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("reports", sa.Integer(), server_default="1", nullable=False),
        sa.Column("reason", sa.String(32), nullable=False),
        sa.Column("status_code", sa.String(16), nullable=True),
        sa.Column("diagnostic", sa.Text(), nullable=True),
        sa.Column("first_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_report_id", sa.String(255), nullable=True),
        sa.Column("email_log_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "kind IN ('permanent', 'soft')", name=op.f("ck_email_undeliverable_kind")
        ),
        sa.ForeignKeyConstraint(
            ["email_log_id"],
            ["email_log.id"],
            name=op.f("fk_email_undeliverable_email_log_id_email_log"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_email_undeliverable")),
    )
    op.create_index("uq_email_undeliverable_email", "email_undeliverable", ["email"], unique=True)
    op.execute(
        "CREATE TRIGGER trg_email_undeliverable_updated_at BEFORE UPDATE ON email_undeliverable "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
    )


def downgrade() -> None:
    op.drop_table("email_undeliverable")
    op.drop_index("ix_email_log_message_id", table_name="email_log")
    op.drop_column("email_log", "bounce_message_id")
    op.drop_column("email_log", "bounce_reason")
    op.drop_column("email_log", "bounce_status")
    op.drop_column("email_log", "bounced_at")
    op.drop_column("email_log", "message_id")
