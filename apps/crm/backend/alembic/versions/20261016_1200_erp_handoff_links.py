"""erp_handoff_links: привязка клиентов и сделок к ERP (M3-CRM-03, ADR-0022)

Revision ID: 0023_erp_handoff_links
Revises: 0022_external_services
Create Date: 2026-10-16 12:00:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0023_erp_handoff_links"
down_revision: str | None = "0022_external_services"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("clients", sa.Column("erp_company_id", sa.BigInteger(), nullable=True))
    op.create_index("ix_clients_erp_company_id", "clients", ["erp_company_id"])

    op.add_column("deals", sa.Column("erp_deal_id", sa.BigInteger(), nullable=True))
    op.add_column("deals", sa.Column("external_stage", sa.String(length=64), nullable=True))
    op.create_index("ix_deals_erp_deal_id", "deals", ["erp_deal_id"])


def downgrade() -> None:
    op.drop_index("ix_deals_erp_deal_id", table_name="deals")
    op.drop_column("deals", "external_stage")
    op.drop_column("deals", "erp_deal_id")

    op.drop_index("ix_clients_erp_company_id", table_name="clients")
    op.drop_column("clients", "erp_company_id")
