"""deals: сделки клиента — продукт, сумма, стадия, причина итога (Q-013, ADR-0019)

Revision ID: 0015_deals
Revises: 0014_client_contacts
Create Date: 2026-10-12 13:10:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015_deals"
down_revision: str | None = "0014_client_contacts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "deals",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("client_id", sa.BigInteger(), nullable=True),
        sa.Column("lead_id", sa.BigInteger(), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("product_key", sa.String(length=64), nullable=True),
        sa.Column("amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("currency", sa.CHAR(3), server_default=sa.text("'UZS'"), nullable=False),
        sa.Column("stage", sa.String(length=8), server_default=sa.text("'open'"), nullable=False),
        sa.Column("expected_close_date", sa.Date(), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lost_reason", sa.String(length=120), nullable=True),
        sa.Column("owner_user_id", sa.BigInteger(), nullable=True),
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
        sa.CheckConstraint("stage IN ('open', 'won', 'lost')", name=op.f("ck_deals_stage")),
        sa.CheckConstraint("amount IS NULL OR amount >= 0", name=op.f("ck_deals_amount")),
        sa.ForeignKeyConstraint(
            ["client_id"],
            ["clients.id"],
            name=op.f("fk_deals_client_id_clients"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["lead_id"], ["leads.id"], name=op.f("fk_deals_lead_id_leads"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            name=op.f("fk_deals_owner_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_deals")),
    )
    op.create_index("ix_deals_client_id", "deals", ["client_id"])
    op.create_index("ix_deals_lead_id", "deals", ["lead_id"])
    op.create_index("ix_deals_stage_closed_at", "deals", ["stage", "closed_at"])
    op.execute(
        "CREATE TRIGGER trg_deals_updated_at BEFORE UPDATE ON deals "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_deals_updated_at ON deals")
    op.drop_index("ix_deals_stage_closed_at", table_name="deals")
    op.drop_index("ix_deals_lead_id", table_name="deals")
    op.drop_index("ix_deals_client_id", table_name="deals")
    op.drop_table("deals")
