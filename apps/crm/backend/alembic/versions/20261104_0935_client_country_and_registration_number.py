"""clients: страна и рег. номер иностранной компании (PART-CRM), индексы поиска

Revision ID: fefcc20f861d
Revises: 97bc02846729
Create Date: 2026-11-04 09:35:59.381452+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "fefcc20f861d"
down_revision: str | Sequence[str] | None = "97bc02846729"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("clients", sa.Column("country", sa.String(length=2), nullable=True))
    op.add_column("clients", sa.Column("registration_number", sa.String(length=64), nullable=True))
    op.create_index("ix_clients_inn", "clients", ["inn"])
    op.create_index(
        "ix_clients_country_registration_number",
        "clients",
        ["country", "registration_number"],
        postgresql_where=sa.text("registration_number IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_clients_country_registration_number", table_name="clients")
    op.drop_index("ix_clients_inn", table_name="clients")
    op.drop_column("clients", "registration_number")
    op.drop_column("clients", "country")
