"""Lead outcome «handed over as a partner» (ЛП-1): `discarded_kind = 'partner'` + ERP
application id.

`leads.partner_application_id` — the partner application the lead was handed over as (ERP id);
set together with
`discarded_kind = 'partner'`. The check constraint on `discarded_kind` gains the new value.
Downgrade restores the
old constraint (leads already handed over as partners are put back to `NULL` first) and drops
the column.

Revision ID: 331d20a4cab7
Revises: 9c3f1d5a62e7
Create Date: 2026-11-25 06:03:27.981170+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "331d20a4cab7"
down_revision: str | Sequence[str] | None = "9c3f1d5a62e7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CHECK = "ck_leads_discarded_kind"


def upgrade() -> None:
    op.add_column("leads", sa.Column("partner_application_id", sa.BigInteger(), nullable=True))
    op.drop_constraint(op.f(_CHECK), "leads", type_="check")
    op.create_check_constraint(
        op.f(_CHECK),
        "leads",
        "discarded_kind IS NULL OR discarded_kind IN ('spam', 'test', 'duplicate', 'partner')",
    )


def downgrade() -> None:
    op.execute("UPDATE leads SET discarded_kind = NULL WHERE discarded_kind = 'partner'")
    op.drop_constraint(op.f(_CHECK), "leads", type_="check")
    op.create_check_constraint(
        op.f(_CHECK),
        "leads",
        "discarded_kind IS NULL OR discarded_kind IN ('spam', 'test', 'duplicate')",
    )
    op.drop_column("leads", "partner_application_id")
