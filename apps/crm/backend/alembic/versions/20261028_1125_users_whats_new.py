"""users whats_new: отметки «Что нового» (W-REL)

Две колонки `users`: `whats_new_shown` — до какой записи «Что нового» (дата записи, `2026-10-28`)
сотруднику уже показано окно «Платформа обновлена», и `whats_new_read` — до какой записи он открыл
«Что нового» (пока не открыл — у «?» в шапке отметка «Новое»). Флаги хранит CRM, как
`onboarding_done_at` (W15-H7), а не браузер. NULL — ещё ничего не видел: существующие сотрудники
увидят окно один раз после первой выкладки с записью.

Revision ID: 9362ca08ba13
Revises: 0048_base_role_by_matrix
Create Date: 2026-10-28 11:25:17.450508+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9362ca08ba13"
down_revision: str | Sequence[str] | None = "0048_base_role_by_matrix"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("whats_new_shown", sa.String(length=10), nullable=True))
    op.add_column("users", sa.Column("whats_new_read", sa.String(length=10), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "whats_new_read")
    op.drop_column("users", "whats_new_shown")
