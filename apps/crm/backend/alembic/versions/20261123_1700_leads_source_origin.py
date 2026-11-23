"""Lead origin facts (LID-5): form key, landing path, referrer, UTM, landing language.

Nullable columns on `leads`; existing leads keep their known channel (`source`) and get no origin
facts. Downgrade drops the columns.

Revision ID: 7b1e3c9a52d4
Revises: 4d6593eef5f9
Create Date: 2026-11-23 17:00:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "7b1e3c9a52d4"
down_revision: str | Sequence[str] | None = "4d6593eef5f9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("leads", sa.Column("source_form", sa.String(64), nullable=True))
    op.add_column("leads", sa.Column("source_page", sa.String(512), nullable=True))
    op.add_column("leads", sa.Column("source_referrer", sa.String(512), nullable=True))
    op.add_column("leads", sa.Column("source_utm", JSONB(), nullable=True))
    op.add_column("leads", sa.Column("source_lang", sa.String(8), nullable=True))


def downgrade() -> None:
    op.drop_column("leads", "source_lang")
    op.drop_column("leads", "source_utm")
    op.drop_column("leads", "source_referrer")
    op.drop_column("leads", "source_page")
    op.drop_column("leads", "source_form")
