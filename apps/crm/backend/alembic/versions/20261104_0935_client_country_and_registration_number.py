"""clients: страна и рег. номер иностранной компании, заявки партнёров на подтверждение (PART-CRM)

Revision ID: fefcc20f861d
Revises: 97bc02846729
Create Date: 2026-11-04 09:35:59.381452+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "fefcc20f861d"
down_revision: str | Sequence[str] | None = "97bc02846729"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("clients", sa.Column("country", sa.String(length=2), nullable=True))
    op.add_column("clients", sa.Column("registration_number", sa.String(length=64), nullable=True))
    op.create_table(
        "partner_client_requests",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("client_id", sa.BigInteger(), nullable=False),
        sa.Column("erp_company_id", sa.BigInteger(), nullable=False),
        sa.Column("matched_by", sa.String(length=24), nullable=False),
        sa.Column(
            "status", sa.String(length=12), server_default=sa.text("'pending'"), nullable=False
        ),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("decided_by_user_id", sa.BigInteger(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
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
            "status IN ('pending', 'confirmed', 'declined')",
            name=op.f("ck_partner_client_requests_status"),
        ),
        sa.ForeignKeyConstraint(
            ["client_id"],
            ["clients.id"],
            name=op.f("fk_partner_client_requests_client_id_clients"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["decided_by_user_id"],
            ["users.id"],
            name=op.f("fk_partner_client_requests_decided_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_partner_client_requests")),
    )
    op.create_index(
        "ix_partner_client_requests_client_id", "partner_client_requests", ["client_id"]
    )
    op.create_index(
        "uq_partner_client_requests_pending",
        "partner_client_requests",
        ["erp_company_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.execute(
        "CREATE TRIGGER trg_partner_client_requests_updated_at BEFORE UPDATE "
        "ON partner_client_requests FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
    )


def downgrade() -> None:
    op.drop_index("uq_partner_client_requests_pending", table_name="partner_client_requests")
    op.drop_index("ix_partner_client_requests_client_id", table_name="partner_client_requests")
    op.drop_table("partner_client_requests")
    op.drop_column("clients", "registration_number")
    op.drop_column("clients", "country")
