"""Письмо из общего ящика: источник и повтор регистрации (W18A-P2-3)

`letters.source_mail_id` — id письма общего ящика CRM (`source.crm_inbound_mail_id` формы регистрации); частичный
уникальный индекс `uq_letters_source_mail_id` (`WHERE source_mail_id IS NOT NULL`): одно письмо ящика — один ВХ.
Повторная регистрация возвращает уже созданный ВХ (200), гонка двух вставок упирается в индекс. Письма,
зарегистрированные до этой ревизии, поля не имеют (источник был только в событии). Откат снимает индекс и поле.

Revision ID: b8774e6a6f55
Revises: fc4be7c40e67
Create Date: 2026-11-03 04:25:28.676606+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b8774e6a6f55"
down_revision: str | Sequence[str] | None = "fc4be7c40e67"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("letters", sa.Column("source_mail_id", sa.BigInteger(), nullable=True))
    op.create_index(
        "uq_letters_source_mail_id",
        "letters",
        ["source_mail_id"],
        unique=True,
        postgresql_where=sa.text("source_mail_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_letters_source_mail_id", table_name="letters")
    op.drop_column("letters", "source_mail_id")
