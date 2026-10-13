"""service_requests: итог для клиента и время закрытия (аудит 2026-10-09, ADR-0015)

Revision ID: 0009_service_request_resolution
Revises: 0008_system_alerts
Create Date: 2026-10-09 12:00:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_service_request_resolution"
down_revision: str | Sequence[str] | None = "0008_system_alerts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("service_requests", sa.Column("resolution", sa.Text(), nullable=True))
    op.add_column(
        "service_requests", sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("service_requests", "closed_at")
    op.drop_column("service_requests", "resolution")
