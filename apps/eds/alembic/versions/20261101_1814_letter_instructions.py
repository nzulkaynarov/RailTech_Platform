"""Поручения по входящим письмам (P8b, SPEC-v3 §3.2a п. 2–5; бенчмарк СЭД 2026-11-01 §6.2–6.3)

Путь делопроизводства: статусы письма `in_execution`, `executed`, `noted`; тип резолюции, «на контроле», проект
резолюции делопроизводителя, когда исполнено. Таблицы поручений (`instructions`), переносов срока
(`instruction_extensions`) и ознакомления (`letter_acquaintances`); файлы отчёта — владелец `files.instruction_id`.
Downgrade удаляет таблицы и поля; письма в новых статусах при откате переводятся в `resolved`.

Revision ID: be9417052e71
Revises: 7d0f20a58e24
Create Date: 2026-11-01 18:14:46.423997+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "be9417052e71"
down_revision: str | Sequence[str] | None = "7d0f20a58e24"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_STATUSES = "status IN ('awaiting_resolution', 'resolved', 'returned', 'rejected')"
_NEW_STATUSES = (
    "status IN ('awaiting_resolution', 'resolved', 'returned', 'rejected', 'in_execution', 'executed', 'noted')"
)


def upgrade() -> None:
    op.add_column("letters", sa.Column("resolution_kind", sa.String(length=16), nullable=True))
    op.add_column("letters", sa.Column("on_control", sa.Boolean(), server_default=sa.text("false"), nullable=False))
    op.add_column("letters", sa.Column("resolution_draft", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column("letters", sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True))
    op.drop_constraint(op.f("ck_letters_status"), "letters", type_="check")
    op.create_check_constraint(op.f("ck_letters_status"), "letters", _NEW_STATUSES)
    op.create_check_constraint(
        op.f("ck_letters_resolution_kind"),
        "letters",
        "resolution_kind IS NULL OR resolution_kind IN ('execute', 'reply', 'info')",
    )
    op.create_index("ix_letters_on_control", "letters", ["on_control"], postgresql_where=sa.text("on_control"))

    op.create_table(
        "instructions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("letter_id", sa.Uuid(), nullable=False),
        sa.Column("crm_user_id", sa.BigInteger(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("due", sa.Date(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("report", sa.Text(), nullable=True),
        sa.Column("outgoing_document_id", sa.Uuid(), nullable=True),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reminders_sent", sa.ARRAY(sa.Text()), server_default=sa.text("'{}'::text[]"), nullable=False),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("kind IN ('execute', 'reply')", name=op.f("ck_instructions_kind")),
        sa.CheckConstraint("role IN ('responsible', 'co_executor')", name=op.f("ck_instructions_role")),
        sa.CheckConstraint("status IN ('in_work', 'executed')", name=op.f("ck_instructions_status")),
        sa.ForeignKeyConstraint(
            ["letter_id"], ["letters.id"], name=op.f("fk_instructions_letter_id_letters"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["outgoing_document_id"],
            ["documents.id"],
            name=op.f("fk_instructions_outgoing_document_id_documents"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_instructions")),
        sa.UniqueConstraint("letter_id", "crm_user_id", name="uq_instructions_letter_person"),
    )
    op.create_index(op.f("ix_instructions_letter_id"), "instructions", ["letter_id"])
    op.create_index("ix_instructions_person_status", "instructions", ["crm_user_id", "status"])
    op.create_index("ix_instructions_status_due", "instructions", ["status", "due"])

    op.create_table(
        "instruction_extensions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("instruction_id", sa.Uuid(), nullable=False),
        sa.Column("old_due", sa.Date(), nullable=False),
        sa.Column("new_due", sa.Date(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("requested_by", sa.BigInteger(), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_by", sa.BigInteger(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected')", name=op.f("ck_instruction_extensions_status")
        ),
        sa.ForeignKeyConstraint(
            ["instruction_id"],
            ["instructions.id"],
            name=op.f("fk_instruction_extensions_instruction_id_instructions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_instruction_extensions")),
    )
    op.create_index(op.f("ix_instruction_extensions_instruction_id"), "instruction_extensions", ["instruction_id"])
    op.create_index(
        "uq_instruction_extensions_pending",
        "instruction_extensions",
        ["instruction_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )

    op.create_table(
        "letter_acquaintances",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("letter_id", sa.Uuid(), nullable=False),
        sa.Column("crm_user_id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["letter_id"], ["letters.id"], name=op.f("fk_letter_acquaintances_letter_id_letters"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_letter_acquaintances")),
        sa.UniqueConstraint("letter_id", "crm_user_id", name="uq_letter_acquaintances_letter_person"),
    )
    op.create_index("ix_letter_acquaintances_person", "letter_acquaintances", ["crm_user_id", "acknowledged_at"])

    op.add_column("files", sa.Column("instruction_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_files_instruction_id_instructions"),
        "files",
        "instructions",
        ["instruction_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(op.f("ix_files_instruction_id"), "files", ["instruction_id"])
    op.drop_constraint(op.f("ck_files_one_owner"), "files", type_="check")
    op.create_check_constraint(
        op.f("ck_files_one_owner"), "files", "num_nonnulls(letter_id, document_id, instruction_id) <= 1"
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_files_one_owner"), "files", type_="check")
    op.execute("DELETE FROM files WHERE instruction_id IS NOT NULL")
    op.create_check_constraint(op.f("ck_files_one_owner"), "files", "letter_id IS NULL OR document_id IS NULL")
    op.drop_index(op.f("ix_files_instruction_id"), table_name="files")
    op.drop_constraint(op.f("fk_files_instruction_id_instructions"), "files", type_="foreignkey")
    op.drop_column("files", "instruction_id")
    op.drop_index("ix_letter_acquaintances_person", table_name="letter_acquaintances")
    op.drop_table("letter_acquaintances")
    op.drop_index("uq_instruction_extensions_pending", table_name="instruction_extensions")
    op.drop_index(op.f("ix_instruction_extensions_instruction_id"), table_name="instruction_extensions")
    op.drop_table("instruction_extensions")
    op.drop_index("ix_instructions_status_due", table_name="instructions")
    op.drop_index("ix_instructions_person_status", table_name="instructions")
    op.drop_index(op.f("ix_instructions_letter_id"), table_name="instructions")
    op.drop_table("instructions")
    op.drop_index("ix_letters_on_control", table_name="letters")
    op.drop_constraint(op.f("ck_letters_resolution_kind"), "letters", type_="check")
    op.drop_constraint(op.f("ck_letters_status"), "letters", type_="check")
    op.execute("UPDATE letters SET status = 'resolved' WHERE status IN ('in_execution', 'executed', 'noted')")
    op.create_check_constraint(op.f("ck_letters_status"), "letters", _OLD_STATUSES)
    for column in ("executed_at", "resolution_draft", "on_control", "resolution_kind"):
        op.drop_column("letters", column)
