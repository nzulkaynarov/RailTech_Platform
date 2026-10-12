"""llm_usage: единый учёт вызовов моделей (аудит 2026-10-12 §3 п. 5, ADR-0014)

Revision ID: 0011_llm_usage
Revises: 0010_integration_secrets
Create Date: 2026-10-12 12:20:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_llm_usage"
down_revision: str | None = "0010_integration_secrets"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "llm_usage",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("purpose", sa.String(32), nullable=False),
        sa.Column("alias", sa.String(64), nullable=False),
        sa.Column("provider", sa.String(32), nullable=True),
        sa.Column("model", sa.String(128), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("cost_usd", sa.Float(), nullable=False),
        sa.Column("lead_id", sa.BigInteger(), nullable=True),
        sa.Column("kind", sa.String(8), nullable=False),
        sa.CheckConstraint("kind IN ('work', 'test')", name=op.f("ck_llm_usage_kind")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_llm_usage")),
    )
    op.create_index(op.f("ix_llm_usage_at"), "llm_usage", ["at"])


def downgrade() -> None:
    op.drop_index(op.f("ix_llm_usage_at"), table_name="llm_usage")
    op.drop_table("llm_usage")
