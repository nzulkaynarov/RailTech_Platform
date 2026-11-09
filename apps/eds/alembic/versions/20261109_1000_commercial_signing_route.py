"""Маршрут подписи коммерческого документа ERP (SIGN-4, FX-10).

Revision ID: c1f4a9e2d7b3
Revises: c444cfe94f0d
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "c1f4a9e2d7b3"
down_revision: str | Sequence[str] | None = "c444cfe94f0d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEX = "uq_approval_routes_signing_version"


def upgrade() -> None:
    op.add_column("approval_routes", sa.Column("signing_snapshot", JSONB(), nullable=True))
    op.drop_constraint("template", "approval_routes", type_="check")
    op.create_check_constraint(
        "template",
        "approval_routes",
        "template IN ('memo', 'application', 'report', 'quote', 'signing')",
    )
    op.execute(
        f"CREATE UNIQUE INDEX {INDEX} ON approval_routes "
        "((signing_snapshot->>'kind'), (signing_snapshot->>'object_id'), (coalesce(signing_snapshot->>'version', ''))) "
        "WHERE template = 'signing' AND status IN ('open', 'approved')"
    )


def downgrade() -> None:
    op.execute(f"DROP INDEX {INDEX}")
    op.drop_constraint("template", "approval_routes", type_="check")
    op.create_check_constraint("template", "approval_routes", "template IN ('memo', 'application', 'report', 'quote')")
    op.drop_column("approval_routes", "signing_snapshot")
