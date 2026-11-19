"""Исход исходящего письма: отметка «вручено иначе» (СЦ-1, стандарт интерфейса §14 п. 1).

`documents.mail_waived_at` и `mail_waived_by`: сотрудник снял отправку почтой — письмо вручено нарочным или через
портал. Без отметки письмо с почтой адресата считается недоставленным, пока попытка отправки не завершилась успехом, и
остаётся в «Исходящих». На проде на 2026-11-19 такое письмо одно (OUT-005/26, почта не была подключена); у остальных
четырёх исходящих почты адресата нет — они остаются в «Архиве». Откат удаляет колонки.

Revision ID: 3e8a5c1f9b24
Revises: 7c41e2b9d5f3
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "3e8a5c1f9b24"
down_revision: str | Sequence[str] | None = "7c41e2b9d5f3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("mail_waived_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("documents", sa.Column("mail_waived_by", sa.BigInteger(), nullable=True))


def downgrade() -> None:
    op.drop_column("documents", "mail_waived_by")
    op.drop_column("documents", "mail_waived_at")
