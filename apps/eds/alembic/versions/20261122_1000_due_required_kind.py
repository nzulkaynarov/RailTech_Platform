"""СЦ-11: вид «Требование или уведомление ГНК» требует срок по документу (`attrs.due_required`).

Флаг — данные справочника `letter-kinds`: администратор ставит и снимает его у любого вида. Здесь он выставлен только
стартовому виду `tax_notice`; у остальных видов ключа нет — читается как «нет». Откат убирает ключ.

Revision ID: c3a8e1f07d52
Revises: 5b7e2d9a4c61
Create Date: 2026-11-22 10:00:00.000000+00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c3a8e1f07d52"
down_revision: str | Sequence[str] | None = "5b7e2d9a4c61"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "UPDATE dictionary_items SET attrs = attrs || '{\"due_required\": true}'::jsonb "
        "WHERE kind = 'letter-kinds' AND code = 'tax_notice' AND NOT (attrs ? 'due_required')"
    )


def downgrade() -> None:
    op.execute("UPDATE dictionary_items SET attrs = attrs - 'due_required' WHERE kind = 'letter-kinds'")
