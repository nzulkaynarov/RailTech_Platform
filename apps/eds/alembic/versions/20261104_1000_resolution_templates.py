"""Шаблоны резолюций и названия видов резолюции справочником (EDS-REG, R2)

Таблица `resolution_templates` — личные и общие шаблоны резолюций пути делопроизводства. В справочник засеваются
названия видов резолюции (`resolution-kinds`: `execute`, `reply`, `info` — поведение кода, список закрытый: только
переименовать и переставить). Downgrade удаляет таблицу и значения справочника.

Revision ID: 549002bb5ead
Revises: e2bd0879b468
Create Date: 2026-11-04 10:00:00+00:00
"""

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "549002bb5ead"
down_revision: str | Sequence[str] | None = "e2bd0879b468"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RESOLUTION_KINDS = (
    ("execute", "К исполнению", "Ijro uchun", "For execution"),
    ("reply", "Подготовить ответ", "Javob tayyorlash", "Prepare a reply"),
    ("info", "Для сведения", "Ma’lumot uchun", "For information"),
)


def upgrade() -> None:
    op.create_table(
        "resolution_templates",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("scope", sa.String(length=16), nullable=False),
        sa.Column("owner_crm_user_id", sa.BigInteger(), nullable=True),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("responsible_type", sa.String(length=16), server_default=sa.text("'none'"), nullable=False),
        sa.Column("responsible_crm_user_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "co_executor_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "acquaint_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("due_days", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("scope IN ('personal', 'company')", name=op.f("ck_resolution_templates_scope")),
        sa.CheckConstraint("kind IN ('execute', 'reply', 'info')", name=op.f("ck_resolution_templates_kind")),
        sa.CheckConstraint(
            "responsible_type IN ('person', 'addressee', 'none')", name=op.f("ck_resolution_templates_responsible_type")
        ),
        sa.CheckConstraint(
            "(scope = 'personal') = (owner_crm_user_id IS NOT NULL)",
            name=op.f("ck_resolution_templates_owner_by_scope"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_resolution_templates")),
    )
    op.create_index("ix_resolution_templates_owner", "resolution_templates", ["owner_crm_user_id"], unique=False)
    now = datetime.now(UTC)
    items = sa.table(
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
        items,
        [
            {
                "kind": "resolution-kinds",
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
            for index, (code, ru, uz, en) in enumerate(RESOLUTION_KINDS)
        ],
    )


def downgrade() -> None:
    op.execute("DELETE FROM dictionary_items WHERE kind = 'resolution-kinds'")
    op.drop_index("ix_resolution_templates_owner", table_name="resolution_templates")
    op.drop_table("resolution_templates")
