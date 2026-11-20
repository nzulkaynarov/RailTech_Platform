"""СЦ-5: `letters.previous_number` и `documents.previous_number` — номер до перенумерации.

Выданные номера с кириллическим обозначением (ВХ-001/26, ИСХ-001/26, СЗ-…, ЗЯ-…) переводятся на латиницу командой
`python -m app renumber-latin`; прежний номер остаётся в этой колонке, показывается в карточке и находится поиском и
поиском по номеру (старая ссылка). Колонки пустые, пока номер не менялся. Откат удаляет колонки.

Revision ID: 99d980a0287c
Revises: 3e8a5c1f9b24
Create Date: 2026-11-20 19:17:31.644477+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "99d980a0287c"
down_revision: str | Sequence[str] | None = "3e8a5c1f9b24"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("letters", sa.Column("previous_number", sa.String(length=32), nullable=True))
    op.create_index(op.f("ix_letters_previous_number"), "letters", ["previous_number"], unique=False)
    op.add_column("documents", sa.Column("previous_number", sa.String(length=32), nullable=True))
    op.create_index(op.f("ix_documents_previous_number"), "documents", ["previous_number"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_documents_previous_number"), table_name="documents")
    op.drop_column("documents", "previous_number")
    op.drop_index(op.f("ix_letters_previous_number"), table_name="letters")
    op.drop_column("letters", "previous_number")
