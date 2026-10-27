"""identity_catalog_state: отпечаток каталога прав EDS для автопереопубликации (W13C-F4)

CRM при старте воркера сравнивает отпечаток каталога прав EDS (`platform-rbac.yaml`) с записанным
здесь и при расхождении переопубликует `identity.user.updated` всем сотрудникам (Q-W13-A2-3,
вариант 2). Таблица пустая: первый старт запишет отпечаток (и переопубликует, если сотрудники уже
есть). Данных для переноса нет.

Revision ID: 0040_identity_catalog_state
Revises: 0039_rt_bus
Create Date: 2026-10-27 10:00:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0040_identity_catalog_state"
down_revision: str | None = "0039_rt_bus"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "identity_catalog_state",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("published_users", sa.Integer(), nullable=False),
        sa.Column(
            "published_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_identity_catalog_state")),
    )


def downgrade() -> None:
    op.drop_table("identity_catalog_state")
