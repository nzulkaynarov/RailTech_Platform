"""clients: состояние передачи в бэк-офис ERP (FIX-31, I-5, I-20)

Передача клиента идёт задачей после коммита клиента: менеджер видит «передаётся / передан /
ошибка (код)» в карточке клиента. `erp_handoff_request` — заявку в ERP ещё нужно завести (не
теряется при повторе после сбоя).

Revision ID: 0027_client_erp_handoff
Revises: 0026_user_platform_access
Create Date: 2026-10-20 14:00:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0027_client_erp_handoff"
down_revision: str | None = "0026_user_platform_access"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("clients", sa.Column("erp_handoff_status", sa.String(length=16), nullable=True))
    op.add_column("clients", sa.Column("erp_handoff_error", sa.String(length=500), nullable=True))
    op.add_column(
        "clients",
        sa.Column(
            "erp_handoff_request", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
    )
    op.create_check_constraint(
        op.f("ck_clients_erp_handoff_status"),
        "clients",
        "erp_handoff_status IS NULL OR erp_handoff_status IN ('pending', 'done', 'failed')",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_clients_erp_handoff_status"), "clients", type_="check")
    op.drop_column("clients", "erp_handoff_request")
    op.drop_column("clients", "erp_handoff_error")
    op.drop_column("clients", "erp_handoff_status")
