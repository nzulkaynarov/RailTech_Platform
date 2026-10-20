"""erp_webhooks: уникальный erp_deal_id, порядок по occurred_at, сообщения после коммита (FIX-33)

* `deals.erp_deal_id` — уникальный (одна заявка ERP — одно зеркало); существующие дубли свёрнуты:
  остаётся зеркало со связью с лидом (затем самое раннее), у остальных `erp_deal_id` и
  `external_stage` обнулены (строки не удаляются — это обычные локальные сделки);
* `deals.external_stage_at` — `occurred_at` последнего применённого события: старое после нового
  стадию не откатывает;
* `erp_incoming_events`: `attempts` (счётчик неудачных обработок, потолок — `failed`), `outbox` /
  `notified_at` (сообщения в Telegram, которые отправляются после коммита один раз на событие),
  статус `rejected` (событие принято и записано, но отклонено: чужая компания, неизвестный тип),
  `erp_company_id` / `crm_client_id` необязательны (тело отклонённого события может их не нести).

Revision ID: 0028_erp_webhook_reliability
Revises: 0027_client_erp_handoff
Create Date: 2026-10-20 17:00:00+00:00
"""

import logging
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0028_erp_webhook_reliability"
down_revision: str | None = "0027_client_erp_handoff"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DEDUPE_SQL = """
WITH ranked AS (
    SELECT id,
           row_number() OVER (
               PARTITION BY erp_deal_id ORDER BY (lead_id IS NOT NULL) DESC, id ASC
           ) AS rn
    FROM deals
    WHERE erp_deal_id IS NOT NULL
)
UPDATE deals
SET erp_deal_id = NULL, external_stage = NULL
FROM ranked
WHERE deals.id = ranked.id AND ranked.rn > 1
"""


logger = logging.getLogger("alembic.runtime.migration")


def upgrade() -> None:
    collapsed = op.get_bind().execute(sa.text(DEDUPE_SQL)).rowcount
    # Сколько зеркал потеряли связь с ERP: число сверяют с запросом из Q-FIX33-5.
    logger.info(
        "0028: collapsed %d duplicate deals.erp_deal_id (kept the mirror with a lead)", collapsed
    )
    op.drop_index("ix_deals_erp_deal_id", table_name="deals")
    op.create_index("uq_deals_erp_deal_id", "deals", ["erp_deal_id"], unique=True)
    op.add_column(
        "deals", sa.Column("external_stage_at", sa.DateTime(timezone=True), nullable=True)
    )

    op.add_column(
        "erp_incoming_events",
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )
    op.add_column(
        "erp_incoming_events",
        sa.Column("outbox", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "erp_incoming_events", sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.alter_column("erp_incoming_events", "erp_company_id", nullable=True)
    op.alter_column("erp_incoming_events", "crm_client_id", nullable=True)
    op.drop_constraint(op.f("ck_erp_incoming_events_status"), "erp_incoming_events", type_="check")
    op.create_check_constraint(
        op.f("ck_erp_incoming_events_status"),
        "erp_incoming_events",
        "status IN ('received', 'processed', 'failed', 'rejected')",
    )


def downgrade() -> None:
    # Отклонённые события и события без идентификаторов в старой схеме невозможны — не переносятся.
    op.execute(
        "DELETE FROM erp_incoming_events "
        "WHERE status = 'rejected' OR erp_company_id IS NULL OR crm_client_id IS NULL"
    )
    op.drop_constraint(op.f("ck_erp_incoming_events_status"), "erp_incoming_events", type_="check")
    op.create_check_constraint(
        op.f("ck_erp_incoming_events_status"),
        "erp_incoming_events",
        "status IN ('received', 'processed', 'failed')",
    )
    op.alter_column("erp_incoming_events", "crm_client_id", nullable=False)
    op.alter_column("erp_incoming_events", "erp_company_id", nullable=False)
    op.drop_column("erp_incoming_events", "notified_at")
    op.drop_column("erp_incoming_events", "outbox")
    op.drop_column("erp_incoming_events", "attempts")

    op.drop_column("deals", "external_stage_at")
    op.drop_index("uq_deals_erp_deal_id", table_name="deals")
    op.create_index("ix_deals_erp_deal_id", "deals", ["erp_deal_id"])
