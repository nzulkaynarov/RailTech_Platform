"""Шаблоны писем и служебок (TPL-4, план 3.6): `letter_templates` — вид, название, варианты по языкам (тела rt-docs),
«по умолчанию» (один на вид), встроенный ключ (один на ключ). Встроенные добавляет код при первом чтении списка.
Откат удаляет таблицу.

Revision ID: e435ea723f87
Revises: 1ab826e3a38f
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e435ea723f87"
down_revision: str | Sequence[str] | None = "1ab826e3a38f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "letter_templates",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("variants", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("builtin_key", sa.String(32), nullable=True),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column("updated_by", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("kind IN ('letter', 'memo')", name=op.f("ck_letter_templates_kind")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_letter_templates")),
    )
    op.create_index(
        "uq_letter_templates_default", "letter_templates", ["kind"], unique=True, postgresql_where=sa.text("is_default")
    )
    op.create_index(
        "uq_letter_templates_builtin",
        "letter_templates",
        ["builtin_key"],
        unique=True,
        postgresql_where=sa.text("builtin_key IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_letter_templates_builtin", table_name="letter_templates")
    op.drop_index("uq_letter_templates_default", table_name="letter_templates")
    op.drop_table("letter_templates")
