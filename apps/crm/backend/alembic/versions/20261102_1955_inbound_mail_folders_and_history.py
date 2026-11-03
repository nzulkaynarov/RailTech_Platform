"""Входящая почта: папки «Спам» и загрузка истории (W18A-P2-2)

* `inbound_mail.status` — ещё значение `spam` (письмо из спам-папки, вкладка «Подозрительные»);
* `inbound_mail.from_history` — письмо из «Загрузить письма за период» старше окна задач;
* `inbound_mail_import` — загрузка истории: период, ход и итог.

Состояние UID и UIDVALIDITY уже ведётся на папку (`inbound_mailbox`, ключ — имя папки), новых
столбцов не нужно. Откат: письма `spam` уходят в архив с причиной, таблица загрузок удаляется.

Revision ID: add9f58d0dab
Revises: 377806fa51cd
Create Date: 2026-11-02 19:55:15.655740+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "add9f58d0dab"
down_revision: str | Sequence[str] | None = "377806fa51cd"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD = "status IN ('new', 'registered', 'lead', 'archived')"
_NEW = "status IN ('new', 'spam', 'registered', 'lead', 'archived')"


def upgrade() -> None:
    op.drop_constraint(op.f("ck_inbound_mail_status"), "inbound_mail", type_="check")
    op.create_check_constraint(op.f("ck_inbound_mail_status"), "inbound_mail", _NEW)
    op.add_column(
        "inbound_mail",
        sa.Column("from_history", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.create_table(
        "inbound_mail_import",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("days", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="running", nullable=False),
        sa.Column("found", sa.Integer(), server_default="0", nullable=False),
        sa.Column("processed", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created", sa.Integer(), server_default="0", nullable=False),
        sa.Column("limited", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("error_kind", sa.String(length=32), nullable=True),
        sa.Column("requested_by", sa.BigInteger(), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('running', 'done', 'error')", name=op.f("ck_inbound_mail_import_status")
        ),
        sa.CheckConstraint("days BETWEEN 1 AND 366", name=op.f("ck_inbound_mail_import_days")),
        sa.ForeignKeyConstraint(
            ["requested_by"],
            ["users.id"],
            name=op.f("fk_inbound_mail_import_requested_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_inbound_mail_import")),
    )
    op.execute(
        "CREATE TRIGGER trg_inbound_mail_import_updated_at BEFORE UPDATE ON inbound_mail_import "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_inbound_mail_import_updated_at ON inbound_mail_import")
    op.drop_table("inbound_mail_import")
    op.drop_column("inbound_mail", "from_history")
    op.execute(
        "UPDATE inbound_mail SET status = 'archived', "
        "archive_reason = COALESCE(archive_reason, 'Спам') WHERE status = 'spam'"
    )
    op.drop_constraint(op.f("ck_inbound_mail_status"), "inbound_mail", type_="check")
    op.create_check_constraint(op.f("ck_inbound_mail_status"), "inbound_mail", _OLD)
