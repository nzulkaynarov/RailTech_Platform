"""Реестр полномочий подписи и замещение сотрудника (SIGN-2, ADR-0024 п. 1–2, 8)

`signing_authorities` — кто вправе подписывать какие виды документов (массив кодов), лимит суммы и валюта, основание
(устав, приказ, доверенность) с номером, датой и файлом, период, отзыв; инварианты основания — CHECK (доверенность:
номер, дата, срок обязательны, срок не позже даты выдачи плюс 3 года, ГК РУз ст. 139; устав — без номера).
`signing_authority_events` — журнал выдачи, изменения, отзыва. `employees.deputy_*` — проекция замещения из
`identity.user.*` (прав не даёт). Справочник `signing-kinds` засеян стартовыми видами документов; дальше его ведёт
администратор. Откат: таблицы и колонки удаляются вместе с данными; значения справочника `signing-kinds` — тоже.

Revision ID: b333bfe94f0c
Revises: 7f181c0c14fa
Create Date: 2026-11-05 06:47:55.821410+00:00
"""

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b333bfe94f0c"
down_revision: str | Sequence[str] | None = "7f181c0c14fa"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (код, ru, uz, en) — стартовые виды; дальше их ведёт администратор.
SIGNING_KINDS = (
    ("letter_out", "Исходящее письмо", "Chiquvchi xat", "Outgoing letter"),
    ("quote", "Коммерческое предложение", "Tijorat taklifi", "Quotation"),
    ("contract", "Договор", "Shartnoma", "Contract"),
    ("invoice", "Счёт", "Hisob", "Invoice"),
    ("act", "Акт", "Dalolatnoma", "Act"),
    ("memo", "Служебная записка", "Xizmat xati", "Memo"),
)


def upgrade() -> None:
    op.create_table(
        "signing_authorities",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("crm_user_id", sa.BigInteger(), nullable=False),
        sa.Column("kinds", postgresql.ARRAY(sa.String(length=32)), nullable=False),
        sa.Column("limit_amount", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("limit_currency", sa.String(length=3), nullable=True),
        sa.Column("basis", sa.String(length=24), nullable=False),
        sa.Column("basis_number", sa.String(length=64), nullable=True),
        sa.Column("basis_date", sa.Date(), nullable=True),
        sa.Column("file_id", sa.Uuid(), nullable=True),
        sa.Column("vakolat_url", sa.String(length=500), nullable=True),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by", sa.BigInteger(), nullable=True),
        sa.Column("revoke_reason", sa.Text(), nullable=True),
        sa.Column("expiry_notified_for", sa.Date(), nullable=True),
        sa.CheckConstraint(
            "basis IN ('charter', 'order', 'power_of_attorney')", name=op.f("ck_signing_authorities_basis")
        ),
        sa.CheckConstraint("cardinality(kinds) > 0", name=op.f("ck_signing_authorities_kinds_not_empty")),
        sa.CheckConstraint(
            "(limit_amount IS NULL) = (limit_currency IS NULL)", name=op.f("ck_signing_authorities_limit_pair")
        ),
        sa.CheckConstraint(
            "limit_amount IS NULL OR limit_amount > 0", name=op.f("ck_signing_authorities_limit_positive")
        ),
        sa.CheckConstraint("valid_to IS NULL OR valid_to >= valid_from", name=op.f("ck_signing_authorities_period")),
        sa.CheckConstraint(
            "basis <> 'power_of_attorney' OR (basis_number IS NOT NULL AND basis_date IS NOT NULL "
            "AND valid_to IS NOT NULL AND valid_to <= (basis_date + interval '3 years')::date)",
            name=op.f("ck_signing_authorities_power_of_attorney_terms"),
        ),
        sa.CheckConstraint(
            "basis <> 'order' OR (basis_number IS NOT NULL AND basis_date IS NOT NULL)",
            name=op.f("ck_signing_authorities_order_terms"),
        ),
        sa.CheckConstraint(
            "basis <> 'charter' OR basis_number IS NULL", name=op.f("ck_signing_authorities_charter_without_number")
        ),
        sa.CheckConstraint(
            "(revoked_at IS NULL) = (revoked_by IS NULL)", name=op.f("ck_signing_authorities_revoked_pair")
        ),
        sa.ForeignKeyConstraint(
            ["file_id"], ["files.id"], name=op.f("fk_signing_authorities_file_id_files"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_signing_authorities")),
    )
    op.create_index("ix_signing_authorities_user", "signing_authorities", ["crm_user_id", "valid_from"])
    op.create_index("ix_signing_authorities_kinds", "signing_authorities", ["kinds"], postgresql_using="gin")
    op.create_table(
        "signing_authority_events",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("authority_id", sa.Uuid(), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("by_crm_user_id", sa.BigInteger(), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column(
            "details", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["authority_id"],
            ["signing_authorities.id"],
            name=op.f("fk_signing_authority_events_authority_id_signing_authorities"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_signing_authority_events")),
    )
    op.create_index("ix_signing_authority_events_authority", "signing_authority_events", ["authority_id", "id"])
    op.add_column("employees", sa.Column("deputy_crm_user_id", sa.BigInteger(), nullable=True))
    op.add_column("employees", sa.Column("deputy_from", sa.Date(), nullable=True))
    op.add_column("employees", sa.Column("deputy_to", sa.Date(), nullable=True))
    now = datetime.now(UTC)
    table = sa.table(
        "dictionary_items",
        sa.column("kind", sa.String),
        sa.column("code", sa.String),
        sa.column("name_ru", sa.String),
        sa.column("name_uz", sa.String),
        sa.column("name_en", sa.String),
        sa.column("attrs", postgresql.JSONB),
        sa.column("active", sa.Boolean),
        sa.column("position", sa.Integer),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    op.bulk_insert(
        table,
        [
            {
                "kind": "signing-kinds",
                "code": code,
                "name_ru": ru,
                "name_uz": uz,
                "name_en": en,
                "attrs": {},
                "active": True,
                "position": (index + 1) * 10,
                "created_at": now,
                "updated_at": now,
            }
            for index, (code, ru, uz, en) in enumerate(SIGNING_KINDS)
        ],
    )


def downgrade() -> None:
    op.execute("DELETE FROM dictionary_items WHERE kind = 'signing-kinds'")
    op.drop_column("employees", "deputy_to")
    op.drop_column("employees", "deputy_from")
    op.drop_column("employees", "deputy_crm_user_id")
    op.drop_index("ix_signing_authority_events_authority", table_name="signing_authority_events")
    op.drop_table("signing_authority_events")
    op.drop_index("ix_signing_authorities_kinds", table_name="signing_authorities", postgresql_using="gin")
    op.drop_index("ix_signing_authorities_user", table_name="signing_authorities")
    op.drop_table("signing_authorities")
