"""ИИ-помощник «Заполнить из файла»: журнал предложений и настройки документооборота (EDS-REG)

`ai_suggestions` — журнал вызовов без текстов (кто, когда, функция, алиас, версия промпта, источник, итог, токены,
стоимость, решение человека). `docflow_settings` — одна строка: `recognize_scans` (по умолчанию выключено) засевается.
Downgrade удаляет обе таблицы.

Revision ID: fc4be7c40e67
Revises: 549002bb5ead
Create Date: 2026-11-05 10:00:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "fc4be7c40e67"
down_revision: str | Sequence[str] | None = "549002bb5ead"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ai_suggestions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("function", sa.String(length=32), nullable=False),
        sa.Column("alias", sa.String(length=64), nullable=False),
        sa.Column("prompt_version", sa.String(length=16), nullable=False),
        sa.Column("source", sa.String(length=8), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("error_code", sa.String(length=32), nullable=True),
        sa.Column("crm_user_id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("input_tokens", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("output_tokens", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("cost_usd", sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column("decision", sa.String(length=16), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('ok', 'error', 'refusal', 'invalid', 'budget', 'empty')", name=op.f("ck_ai_suggestions_status")
        ),
        sa.CheckConstraint(
            "decision IS NULL OR decision IN ('accepted', 'edited', 'manual')", name=op.f("ck_ai_suggestions_decision")
        ),
        sa.CheckConstraint("source IN ('text', 'image')", name=op.f("ck_ai_suggestions_source")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_suggestions")),
    )
    op.create_index(op.f("ix_ai_suggestions_created_at"), "ai_suggestions", ["created_at"], unique=False)
    op.create_index(op.f("ix_ai_suggestions_crm_user_id"), "ai_suggestions", ["crm_user_id"], unique=False)
    op.create_table(
        "docflow_settings",
        sa.Column("id", sa.SmallInteger(), nullable=False),
        sa.Column("recognize_scans", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("updated_by", sa.BigInteger(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("id = 1", name=op.f("ck_docflow_settings_single_row")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_docflow_settings")),
    )
    op.execute("INSERT INTO docflow_settings (id, recognize_scans) VALUES (1, false)")


def downgrade() -> None:
    op.drop_table("docflow_settings")
    op.drop_index(op.f("ix_ai_suggestions_crm_user_id"), table_name="ai_suggestions")
    op.drop_index(op.f("ix_ai_suggestions_created_at"), table_name="ai_suggestions")
    op.drop_table("ai_suggestions")
