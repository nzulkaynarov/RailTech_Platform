"""Lead discard marker (LH-1): spam / test / duplicate and the lead a duplicate points to.

Nullable columns on `leads`; the active lists skip a lead with `discarded_kind` set. Downgrade
drops the columns.

Revision ID: b7579292dbee
Revises: 5a8e2c1f7b30
Create Date: 2026-11-24 17:00:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b7579292dbee"
down_revision: str | Sequence[str] | None = "5a8e2c1f7b30"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("leads", sa.Column("discarded_kind", sa.String(16), nullable=True))
    op.add_column("leads", sa.Column("duplicate_of_lead_id", sa.BigInteger(), nullable=True))
    op.create_check_constraint(
        op.f("ck_leads_discarded_kind"),
        "leads",
        "discarded_kind IS NULL OR discarded_kind IN ('spam', 'test', 'duplicate')",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_leads_discarded_kind"), "leads", type_="check")
    op.drop_column("leads", "duplicate_of_lead_id")
    op.drop_column("leads", "discarded_kind")
