"""client_requests: заявка CRM «Создать заявку» на зеркале сделки (W16-D1-2, CRM-03)

Заявку менеджер создаёт в CRM (лид → клиент или новая заявка клиента), в ERP она уходит задачей
после коммита (`erp_create_request`): суть, срочность, контакт с каналом и файл письма директору (id
файла EDS) хранятся на строке `deals` до ответа ERP, состояние передачи — `erp_request_status` /
`erp_request_error`, номер ЗВ/ПР из ERP — `erp_number` (обновляют события ERP). Старые сделки — без
заявки (все поля пустые). Данных для переноса нет.

Revision ID: 0045_client_requests
Revises: 0044_client_notices
Create Date: 2026-10-28 11:00:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0045_client_requests"
down_revision: str | None = "0044_client_notices"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("deals", sa.Column("request_key", sa.Uuid(), nullable=True))
    # Идемпотентность «Создать заявку»: повтор формы с тем же ключом — та же заявка (последний рубеж
    # после блокировки лида или клиента).
    op.create_index("uq_deals_request_key", "deals", ["request_key"], unique=True)
    op.add_column("deals", sa.Column("request_summary", sa.Text(), nullable=True))
    op.add_column("deals", sa.Column("request_urgency", sa.String(length=8), nullable=True))
    op.add_column("deals", sa.Column("request_letter_file_id", sa.Uuid(), nullable=True))
    op.add_column(
        "deals",
        sa.Column(
            "request_contact_id",
            sa.BigInteger(),
            sa.ForeignKey(
                "client_contacts.id",
                name=op.f("fk_deals_request_contact_id_client_contacts"),
                ondelete="SET NULL",
            ),
            nullable=True,
        ),
    )
    op.add_column("deals", sa.Column("erp_request_status", sa.String(length=16), nullable=True))
    op.add_column("deals", sa.Column("erp_request_error", sa.String(length=500), nullable=True))
    op.add_column("deals", sa.Column("erp_number", sa.String(length=32), nullable=True))
    op.create_check_constraint(
        op.f("ck_deals_request_urgency"),
        "deals",
        "request_urgency IS NULL OR request_urgency IN ('normal', 'urgent')",
    )
    op.create_check_constraint(
        op.f("ck_deals_erp_request_status"),
        "deals",
        "erp_request_status IS NULL OR erp_request_status IN ('pending', 'done', 'failed')",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_deals_erp_request_status"), "deals", type_="check")
    op.drop_constraint(op.f("ck_deals_request_urgency"), "deals", type_="check")
    for column in (
        "erp_number",
        "erp_request_error",
        "erp_request_status",
        "request_contact_id",
        "request_letter_file_id",
        "request_urgency",
        "request_summary",
    ):
        op.drop_column("deals", column)
    op.drop_index("uq_deals_request_key", table_name="deals")
    op.drop_column("deals", "request_key")
