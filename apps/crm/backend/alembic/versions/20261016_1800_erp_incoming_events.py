"""erp_incoming_events: таблица входящих вебхуков событий ERP (M3-CRM-04, CONTRACTS §3, ADR-0022)

Revision ID: 0024_erp_incoming_events
Revises: 0023_erp_handoff_links
Create Date: 2026-10-16 18:00:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0024_erp_incoming_events"
down_revision: str | None = "0023_erp_handoff_links"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "erp_incoming_events",
        sa.Column("event_id", sa.String(length=36), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("erp_company_id", sa.BigInteger(), nullable=False),
        sa.Column("crm_client_id", sa.BigInteger(), nullable=False),
        sa.Column("deal_id", sa.BigInteger(), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "status", sa.String(length=16), server_default=sa.text("'received'"), nullable=False
        ),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.CheckConstraint("status IN ('received', 'processed', 'failed')", name="status"),
        sa.ForeignKeyConstraint(["deal_id"], ["deals.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("event_id"),
    )
    op.create_index(
        "ix_erp_incoming_events_crm_client_id", "erp_incoming_events", ["crm_client_id"]
    )
    op.create_index("ix_erp_incoming_events_status", "erp_incoming_events", ["status"])


def downgrade() -> None:
    op.drop_index("ix_erp_incoming_events_status", table_name="erp_incoming_events")
    op.drop_index("ix_erp_incoming_events_crm_client_id", table_name="erp_incoming_events")
    op.drop_table("erp_incoming_events")
