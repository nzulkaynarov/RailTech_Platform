"""Общий ящик как обращение: статусы и итог, «в работе», цепочки, адресаты (W18A-P2-3)

* `inbound_mail.status` — `new | in_work | registering | done | spam`; итог — `outcome`
  (`registered | lead | replied | archived`). Прежние `registered`, `lead`, `archived` переносятся
  в `done` с тем же итогом (кто и когда — `handled_by`, `handled_at` — остаётся);
* исполнитель и время (`assignee_id`, `assigned_at`), начало регистрации ВХ (`registering_at`);
* цепочка: `thread_root_id` (ответ клиента прикреплён к записи), `thread_reply` («Новое (ответ в
  цепочке)»), `activity_at` — последнее входящее письмо цепочки (порядок списка и «прочитано»);
* адресаты: `cc_addrs` отдельно от `to_addrs` (старые строки — всё в `to_addrs`), сотрудники из
  «Кому» и копии (`to_staff_ids`, `cc_staff_ids`), отметка «адресовано лично» (`personal`);
* `inbound_mail_read` — «прочитано» на человека.

Откат: `done` возвращается в прежний статус по итогу (`replied` — в архив с причиной), «в работе» и
«регистрируется» — снова в очередь; цепочечные письма остаются отдельными строками списка.

Revision ID: 563bd9b32ffd
Revises: add9f58d0dab
Create Date: 2026-11-02 21:37:52.952102+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "563bd9b32ffd"
down_revision: str | Sequence[str] | None = "add9f58d0dab"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD = "status IN ('new', 'spam', 'registered', 'lead', 'archived')"
_NEW = "status IN ('new', 'in_work', 'registering', 'done', 'spam')"
_OUTCOME = "outcome IS NULL OR outcome IN ('registered', 'lead', 'replied', 'archived')"
_EMPTY = sa.text("'[]'::jsonb")


def upgrade() -> None:
    table = "inbound_mail"
    op.drop_constraint(op.f("ck_inbound_mail_status"), table, type_="check")
    op.add_column(table, sa.Column("outcome", sa.String(length=16), nullable=True))
    op.execute(
        "UPDATE inbound_mail SET outcome = status, status = 'done' "
        "WHERE status IN ('registered', 'lead', 'archived')"
    )
    op.create_check_constraint(op.f("ck_inbound_mail_status"), table, _NEW)
    op.create_check_constraint(op.f("ck_inbound_mail_outcome"), table, _OUTCOME)

    op.add_column(table, sa.Column("assignee_id", sa.BigInteger(), nullable=True))
    op.add_column(table, sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(table, sa.Column("registering_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(table, sa.Column("thread_root_id", sa.BigInteger(), nullable=True))
    op.add_column(
        table,
        sa.Column("thread_reply", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        table,
        sa.Column(
            "activity_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.execute("UPDATE inbound_mail SET activity_at = LEAST(sent_at, received_at)")
    op.add_column(table, sa.Column("cc_addrs", postgresql.JSONB(), server_default=_EMPTY))
    op.add_column(table, sa.Column("to_staff_ids", postgresql.JSONB(), server_default=_EMPTY))
    op.add_column(table, sa.Column("cc_staff_ids", postgresql.JSONB(), server_default=_EMPTY))
    op.execute("UPDATE inbound_mail SET cc_addrs = '[]', to_staff_ids = '[]', cc_staff_ids = '[]'")
    for name in ("cc_addrs", "to_staff_ids", "cc_staff_ids"):
        op.alter_column(table, name, nullable=False)
    op.add_column(
        table, sa.Column("personal", sa.Boolean(), server_default=sa.false(), nullable=False)
    )
    op.create_foreign_key(
        op.f("fk_inbound_mail_assignee_id_users"),
        table,
        "users",
        ["assignee_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        op.f("fk_inbound_mail_thread_root_id_inbound_mail"),
        table,
        table,
        ["thread_root_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.drop_index("ix_inbound_mail_status_received", table_name=table)
    op.create_index("ix_inbound_mail_status_activity", table, ["status", "activity_at"])
    op.create_index("ix_inbound_mail_assignee_status", table, ["assignee_id", "status"])
    op.create_index("ix_inbound_mail_thread_root", table, ["thread_root_id"])

    op.create_table(
        "inbound_mail_read",
        sa.Column("mail_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "read_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["mail_id"],
            ["inbound_mail.id"],
            name=op.f("fk_inbound_mail_read_mail_id_inbound_mail"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_inbound_mail_read_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("mail_id", "user_id", name=op.f("pk_inbound_mail_read")),
    )


def downgrade() -> None:
    table = "inbound_mail"
    op.drop_table("inbound_mail_read")
    op.drop_index("ix_inbound_mail_thread_root", table_name=table)
    op.drop_index("ix_inbound_mail_assignee_status", table_name=table)
    op.drop_index("ix_inbound_mail_status_activity", table_name=table)
    op.drop_constraint(
        op.f("fk_inbound_mail_thread_root_id_inbound_mail"), table, type_="foreignkey"
    )
    op.drop_constraint(op.f("fk_inbound_mail_assignee_id_users"), table, type_="foreignkey")
    op.drop_constraint(op.f("ck_inbound_mail_status"), table, type_="check")
    op.drop_constraint(op.f("ck_inbound_mail_outcome"), table, type_="check")
    op.execute(
        "UPDATE inbound_mail SET status = CASE "
        "WHEN status IN ('in_work', 'registering') THEN 'new' "
        "WHEN status = 'done' AND outcome IN ('registered', 'lead') THEN outcome "
        "WHEN status = 'done' THEN 'archived' ELSE status END, "
        "archive_reason = CASE WHEN status = 'done' AND outcome = 'replied' "
        "THEN COALESCE(archive_reason, 'Ответ отправлен') ELSE archive_reason END"
    )
    op.create_check_constraint(op.f("ck_inbound_mail_status"), table, _OLD)
    for name in (
        "personal",
        "cc_staff_ids",
        "to_staff_ids",
        "cc_addrs",
        "activity_at",
        "thread_reply",
        "thread_root_id",
        "registering_at",
        "assigned_at",
        "assignee_id",
        "outcome",
    ):
        op.drop_column(table, name)
    op.create_index("ix_inbound_mail_status_received", table, ["status", "received_at"])
