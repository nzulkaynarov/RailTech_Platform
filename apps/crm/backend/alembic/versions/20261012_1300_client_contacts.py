"""client_contacts: контактные лица клиента, один основной на клиента (Q-011, Q-020)

Revision ID: 0014_client_contacts
Revises: 0013_user_notify_flags
Create Date: 2026-10-12 13:00:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_client_contacts"
down_revision: str | None = "0013_user_notify_flags"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "client_contacts",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("client_id", sa.BigInteger(), nullable=False),
        sa.Column("full_name", sa.String(length=255), nullable=False),
        sa.Column("position", sa.String(length=255), nullable=True),
        sa.Column("phone_e164", sa.String(length=20), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("telegram_identity_id", sa.BigInteger(), nullable=True),
        sa.Column("is_primary", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
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
            ["client_id"],
            ["clients.id"],
            name=op.f("fk_client_contacts_client_id_clients"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["telegram_identity_id"],
            ["telegram_identities.id"],
            name=op.f("fk_client_contacts_telegram_identity_id_telegram_identities"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_client_contacts")),
    )
    op.create_index("ix_client_contacts_client_id", "client_contacts", ["client_id"])
    op.create_index(
        "uq_client_contacts_primary",
        "client_contacts",
        ["client_id"],
        unique=True,
        postgresql_where=sa.text("is_primary"),
    )
    op.execute(
        "CREATE TRIGGER trg_client_contacts_updated_at BEFORE UPDATE ON client_contacts "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_client_contacts_updated_at ON client_contacts")
    op.drop_index("uq_client_contacts_primary", table_name="client_contacts")
    op.drop_index("ix_client_contacts_client_id", table_name="client_contacts")
    op.drop_table("client_contacts")
