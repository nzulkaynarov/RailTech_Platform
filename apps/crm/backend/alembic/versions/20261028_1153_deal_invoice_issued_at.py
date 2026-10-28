"""Сделка: когда ERP выставила по ней первый счёт (B-D18-1, W18A-P3)

Зеркало сделки получает `invoice_issued_at` из события шины `erp/invoice.issued` (а также из
`invoice.paid`/`invoice.overdue`, если первое опоздало): это факт «по сделке выставлен счёт», от
которого зависит зона переписки «Счета и оплаты» (`app/domain/chat_access.py`). Стадия зеркала
(`external_stage`) для этого не годится: после «Выставлен счёт» она уходит дальше и может
откатываться событием `deal.stage_changed`, а факт счёта — нет. Синхронных вызовов ERP нет.

Заполнение существующих строк: сделки, чьё зеркало сейчас в стадии `invoiced` или `paid`, получают
время последнего применённого события ERP (`external_stage_at`, иначе `updated_at`). Сделки дальше
по пути (`fulfilment`, `closing`, `won`) не заполняются — по стадии нельзя сказать, был ли счёт;
следующее событие счёта поставит отметку само (на проде живых данных нет).

Revision ID: aa1221ec032b
Revises: 9362ca08ba13
Create Date: 2026-10-28 11:53:20.768799+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "aa1221ec032b"
down_revision: str | Sequence[str] | None = "9362ca08ba13"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("deals", sa.Column("invoice_issued_at", sa.DateTime(timezone=True)))
    op.execute(
        "UPDATE deals SET invoice_issued_at = COALESCE(external_stage_at, updated_at) "
        "WHERE external_stage IN ('invoiced', 'paid')"
    )
    # Зона «Счета и оплаты» ищет сделки клиента со счётом: частичный индекс по клиенту.
    op.create_index(
        "ix_deals_client_id_invoiced",
        "deals",
        ["client_id"],
        postgresql_where=sa.text("invoice_issued_at IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_deals_client_id_invoiced", table_name="deals")
    op.drop_column("deals", "invoice_issued_at")
