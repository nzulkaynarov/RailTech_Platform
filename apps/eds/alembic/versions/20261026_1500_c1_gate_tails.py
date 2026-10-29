"""Хвосты гейта C1: отметка «одобрено с опозданием» у маршрута КП и контакт отправителя письма

Решения архитектора 2026-10-26 (docs/DECISIONS.md, runbook docs/history/runbooks/wave11c-bus-fixes.md, F4):
* `approval_routes.approved_late` — КП одобрено, хотя готово позже срока резолюции (C1-G-1: `due` — предупреждение);
* `letters.sender_contact` — контактное лицо отправителя; письмо по заявке берёт его из `erp.request.created` (C1-G-7).

Revision ID: 0005_c1_gate_tails
Revises: 0004_domain
Create Date: 2026-10-26 15:00:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_c1_gate_tails"
down_revision: str | Sequence[str] | None = "0004_domain"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "approval_routes",
        sa.Column("approved_late", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column("letters", sa.Column("sender_contact", sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column("letters", "sender_contact")
    op.drop_column("approval_routes", "approved_late")
