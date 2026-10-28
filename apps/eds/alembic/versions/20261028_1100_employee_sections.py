"""employees.sections: разделы каталога сотрудника для проверки зоны исполнителя резолюции (D1-8, B-007)

CRM публикует в `identity.user.*` не только коды EDS (`permissions.eds`), но и разделы каталога, которые дают
сотруднику его роли (`permissions.sections`: `erp.calc.goods` -> `full`). EDS при резолюции сверяет, что исполнитель
зоны имеет раздел зоны на уровне `full`. Существующие строки получают пустые разделы до первой переопубликации
(CRM делает её сам при старте воркера после выкладки; вручную — `python -m app republish-identity`).

Revision ID: 0006_employee_sections
Revises: 0005_c1_gate_tails
Create Date: 2026-10-28 11:00:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_employee_sections"
down_revision: str | Sequence[str] | None = "0005_c1_gate_tails"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "employees",
        sa.Column(
            "sections",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("employees", "sections")
