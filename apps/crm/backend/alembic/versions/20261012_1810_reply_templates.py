"""reply_templates: шаблоны быстрых ответов менеджера на ru/uz/en (аудит 2026-10-12 §5)

Revision ID: 0019_reply_templates
Revises: 0018_sandbox_dashboard
Create Date: 2026-10-12 18:00:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0019_reply_templates"
down_revision: str | None = "0018_sandbox_dashboard"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "reply_templates",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("text", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
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
            ["created_by"],
            ["users.id"],
            name=op.f("fk_reply_templates_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reply_templates")),
    )
    op.execute(
        "CREATE TRIGGER trg_reply_templates_updated_at BEFORE UPDATE ON reply_templates "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
    )


def downgrade() -> None:
    op.drop_table("reply_templates")
