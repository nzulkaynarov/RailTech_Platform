"""Срок ссылок на вложения письма в журнале (MAIL-2): `email_log.links_expire_at`.

Письма ERP и EDS приходят со ссылками на вложения, подписанными на срок. «Отправить ещё раз»
скачивает вложения заново, поэтому повтор доступен, пока ссылки живы; ближайший срок хранится
открыто (не секрет). У прежних строк срока нет — письмо с вложениями по ссылкам не повторяется.

Downgrade удаляет колонку.

Revision ID: 87bb4c6ed643
Revises: 09cbac1c437d
Create Date: 2026-11-15 16:00:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "87bb4c6ed643"
down_revision: str | Sequence[str] | None = "09cbac1c437d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "email_log", sa.Column("links_expire_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("email_log", "links_expire_at")
