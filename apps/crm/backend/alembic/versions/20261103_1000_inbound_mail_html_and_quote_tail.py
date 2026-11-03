"""Показ письма: безопасный HTML и свёрнутая цитата (W18A-P2-4)

* `inbound_mail.html_sanitized` — HTML-версия письма после санитизации на сервере (белый список,
  `domain/mail_html.py`); NULL — у старых писем и писем без HTML, они показываются текстом;
* `html_remote_images` — сколько внешних картинок ждут кнопки «Показать картинки»;
* `text_tail` — цитата прошлой переписки и подпись, свёрнутые под «…»; `text` теперь без них (это
  то, что уходит в лид, ВХ, помощнику и в предзаполнение регистрации). У старых писем он пуст.

Откат удаляет три колонки; `text` остаётся как есть (у новых писем он короче — без цитаты).

Revision ID: 76abc53006ad
Revises: 563bd9b32ffd
Create Date: 2026-11-03 10:00:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "76abc53006ad"
down_revision: str | Sequence[str] | None = "563bd9b32ffd"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    table = "inbound_mail"
    op.add_column(table, sa.Column("html_sanitized", sa.Text(), nullable=True))
    op.add_column(
        table,
        sa.Column("html_remote_images", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(table, sa.Column("text_tail", sa.Text(), server_default="", nullable=False))


def downgrade() -> None:
    table = "inbound_mail"
    op.drop_column(table, "text_tail")
    op.drop_column(table, "html_remote_images")
    op.drop_column(table, "html_sanitized")
