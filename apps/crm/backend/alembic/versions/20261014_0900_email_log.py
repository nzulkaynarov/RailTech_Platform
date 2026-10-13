"""email_log: журнал писем сотрудникам коннектора «Почта» (M3-CRM-08)

Revision ID: 0021_email_log
Revises: 0019_reply_templates
Create Date: 2026-10-13 12:00:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021_email_log"
down_revision: str | None = "0020_lead_sources"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "email_log",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("to_email", sa.String(length=255), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("template", sa.String(length=64), nullable=False),
        sa.Column("lang", sa.String(length=2), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        # Тело (временный пароль) — шифртекст Fernet только до отправки, потом NULL.
        sa.Column("body_ciphertext", sa.LargeBinary(), nullable=True),
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        sa.Column("requested_by", sa.BigInteger(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
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
            "status IN ('queued', 'sent', 'failed', 'skipped_no_smtp')",
            name=op.f("ck_email_log_status"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_email_log_user_id_users"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["requested_by"],
            ["users.id"],
            name=op.f("fk_email_log_requested_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_email_log")),
    )
    op.create_index("ix_email_log_created_at", "email_log", ["created_at"])
    op.execute(
        "CREATE TRIGGER trg_email_log_updated_at BEFORE UPDATE ON email_log "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_email_log_updated_at ON email_log")
    op.drop_index("ix_email_log_created_at", table_name="email_log")
    op.drop_table("email_log")
