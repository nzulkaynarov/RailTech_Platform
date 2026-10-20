"""erp_seam: индекс документов ERP по erp_document_id, статус skipped и хеш тела вебхука (FIX-35)

* `documents.erp_document_id` + частичный уникальный индекс `(client_id, erp_document_id)`: событие
  `document.created` — upsert, повтор выпуска не плодит строки (Q-FIX38-1; данных в проде нет);
* `erp_incoming_events.status` допускает `skipped` — событие неизвестного типа принято и записано,
  но не
  обрабатывается (терпимый читатель: новое событие ERP не даёт ни 422, ни ретраев);
* `erp_incoming_events.body_sha256` (+ индекс) — хеш сырого тела: то же тело под другим
  `X-Event-Id` — повтор
  (подпись вебхука не покрывает заголовки), CRM отклоняет такое событие.

Revision ID: 0029_erp_seam_hardening
Revises: 0028_erp_webhook_reliability
Create Date: 2026-10-20 19:00:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0029_erp_seam_hardening"
down_revision: str | None = "0028_erp_webhook_reliability"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("erp_document_id", sa.BigInteger(), nullable=True))
    op.create_index(
        "uq_documents_client_erp_document",
        "documents",
        ["client_id", "erp_document_id"],
        unique=True,
        postgresql_where=sa.text("erp_document_id IS NOT NULL"),
    )

    op.add_column("erp_incoming_events", sa.Column("body_sha256", sa.String(64), nullable=True))
    op.create_index("ix_erp_incoming_events_body_sha256", "erp_incoming_events", ["body_sha256"])
    op.drop_constraint(op.f("ck_erp_incoming_events_status"), "erp_incoming_events", type_="check")
    op.create_check_constraint(
        op.f("ck_erp_incoming_events_status"),
        "erp_incoming_events",
        "status IN ('received', 'processed', 'failed', 'rejected', 'skipped')",
    )


def downgrade() -> None:
    # Пропущенные события в старой схеме невозможны — не переносятся.
    op.execute("DELETE FROM erp_incoming_events WHERE status = 'skipped'")
    op.drop_constraint(op.f("ck_erp_incoming_events_status"), "erp_incoming_events", type_="check")
    op.create_check_constraint(
        op.f("ck_erp_incoming_events_status"),
        "erp_incoming_events",
        "status IN ('received', 'processed', 'failed', 'rejected')",
    )
    op.drop_index("ix_erp_incoming_events_body_sha256", table_name="erp_incoming_events")
    op.drop_column("erp_incoming_events", "body_sha256")

    op.drop_index("uq_documents_client_erp_document", table_name="documents")
    op.drop_column("documents", "erp_document_id")
