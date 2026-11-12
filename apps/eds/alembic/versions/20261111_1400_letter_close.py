"""«Закрыть без ответа» (решение владельца 2026-11-11): статус письма `closed`, причина и пояснение, справочник
`close-reasons` со стартовыми значениями. Откат: колонки, значения справочника и статус удаляются (закрытые письма
возвращаются «На исполнение» — иначе проверка статуса не встанет).

Revision ID: 18acc897173a
Revises: 8e20e8a024d7
"""

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "18acc897173a"
down_revision: str | Sequence[str] | None = "8e20e8a024d7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD = "'awaiting_resolution', 'resolved', 'returned', 'rejected', 'in_execution', 'executed', 'noted', 'duplicate'"
REASONS = (
    ("no_reply_needed", "Ответ не требуется", "Javob talab qilinmaydi", "No reply needed", False),
    ("advertising", "Реклама или рассылка", "Reklama yoki tarqatma", "Advertising or mailing", False),
    ("unreliable_counterparty", "Недобросовестный контрагент", "Insofsiz kontragent", "Unreliable counterparty", True),
    ("other", "Другое", "Boshqa", "Other", True),
)


def upgrade() -> None:
    op.add_column("letters", sa.Column("close_reason", sa.String(32), nullable=True))
    op.add_column("letters", sa.Column("close_comment", sa.Text(), nullable=True))
    op.drop_constraint("status", "letters", type_="check")
    op.create_check_constraint("status", "letters", f"status IN ({OLD}, 'closed')")
    now = datetime.now(UTC)
    table = sa.table(
        "dictionary_items",
        sa.column("kind", sa.String),
        sa.column("code", sa.String),
        sa.column("name_ru", sa.String),
        sa.column("name_uz", sa.String),
        sa.column("name_en", sa.String),
        sa.column("attrs", postgresql.JSONB),
        sa.column("active", sa.Boolean),
        sa.column("position", sa.Integer),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    op.bulk_insert(
        table,
        [
            {
                "kind": "close-reasons",
                "code": code,
                "name_ru": ru,
                "name_uz": uz,
                "name_en": en,
                "attrs": {"comment_required": required},
                "active": True,
                "position": (index + 1) * 10,
                "created_at": now,
                "updated_at": now,
            }
            for index, (code, ru, uz, en, required) in enumerate(REASONS)
        ],
    )


def downgrade() -> None:
    op.execute("DELETE FROM dictionary_items WHERE kind = 'close-reasons'")
    op.execute("UPDATE letters SET status = 'in_execution' WHERE status = 'closed'")
    op.drop_constraint("status", "letters", type_="check")
    op.create_check_constraint("status", "letters", f"status IN ({OLD})")
    op.drop_column("letters", "close_comment")
    op.drop_column("letters", "close_reason")
