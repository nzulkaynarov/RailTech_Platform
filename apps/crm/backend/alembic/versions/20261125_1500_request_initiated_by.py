"""Who started a request and from which registered letter (REZ-1).

Adds `deals.request_initiated_by` and `deals.request_letter_number`. The ERP decides whether a
resolution is needed by the channel, not the screen: `client` (cabinet, bot, form, client letter, a
registered incoming letter) or `staff` (call note, staff entry). Both are sent again on a retry,
so they live on the deal. Downgrade drops both.

Revision ID: b27e41c9d3a8
Revises: 9c3f1d5a62e7
Create Date: 2026-11-25 15:00:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b27e41c9d3a8"
down_revision: str | Sequence[str] | None = "9c3f1d5a62e7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("deals", sa.Column("request_initiated_by", sa.String(8), nullable=True))
    op.add_column("deals", sa.Column("request_letter_number", sa.String(32), nullable=True))


def downgrade() -> None:
    op.drop_column("deals", "request_letter_number")
    op.drop_column("deals", "request_initiated_by")
