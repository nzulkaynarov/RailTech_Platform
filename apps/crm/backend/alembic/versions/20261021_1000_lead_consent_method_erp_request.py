"""leads: способ согласия, отмеченного сотрудником, и заявка ERP, созданная передачей (FIX-57)

* `leads.consent_method` — как получено согласие, если его отметил менеджер (`phone` | `email` |
  `paper`): лид, заведённый вручную, не может подтвердить его в боте (D-8); у согласия из бота
  и формы — NULL;
* `leads.erp_request_id` — заявка ERP, созданная передачей этого лида (D-10): карточка лида
  показывала последнюю сделку лида, а поздние заявки клиента из Cabinet привязываются к тому же
  лиду. Для уже переданных лидов — самая ранняя зеркальная сделка лида (передача идёт раньше
  любой заявки клиента из Cabinet).

Revision ID: 0030_lead_consent_erp_request
Revises: 0029_erp_seam_hardening
Create Date: 2026-10-21 10:00:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0030_lead_consent_erp_request"
down_revision: str | None = "0029_erp_seam_hardening"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("leads", sa.Column("consent_method", sa.String(16), nullable=True))
    op.add_column("leads", sa.Column("erp_request_id", sa.BigInteger(), nullable=True))
    op.execute(
        """
        UPDATE leads
        SET erp_request_id = mirror.erp_deal_id
        FROM (
            SELECT DISTINCT ON (lead_id) lead_id, erp_deal_id
            FROM deals
            WHERE lead_id IS NOT NULL AND erp_deal_id IS NOT NULL
            ORDER BY lead_id, id
        ) AS mirror
        WHERE leads.id = mirror.lead_id
        """
    )


def downgrade() -> None:
    op.drop_column("leads", "erp_request_id")
    op.drop_column("leads", "consent_method")
