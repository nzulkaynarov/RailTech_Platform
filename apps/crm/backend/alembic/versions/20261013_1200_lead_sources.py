"""lead_sources: контакты лида без Telegram — телефон, почта, компания (M3-CRM-05)

Источники `web` / `phone` / `email` / `referral` используют существующую колонку `leads.source`
(ограничения на значения нет, как у `sandbox`). Телефон индексируется: по нему склеиваются
лид с сайта/звонка и Telegram-лид, поделившийся номером (`domain/lead_sources.py`).

Revision ID: 0020_lead_sources
Revises: 0019_reply_templates
Create Date: 2026-10-13 12:00:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020_lead_sources"
down_revision: str | None = "0019_reply_templates"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("leads", sa.Column("phone_e164", sa.String(length=20), nullable=True))
    op.add_column("leads", sa.Column("email", sa.String(length=255), nullable=True))
    op.add_column("leads", sa.Column("company_name", sa.String(length=255), nullable=True))
    op.create_index("ix_leads_phone_e164", "leads", ["phone_e164"])


def downgrade() -> None:
    op.drop_index("ix_leads_phone_e164", table_name="leads")
    op.drop_column("leads", "company_name")
    op.drop_column("leads", "email")
    op.drop_column("leads", "phone_e164")
