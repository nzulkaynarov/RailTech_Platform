"""company_articles: статьи компании — внутренние инструкции для «Помощи» (W18A-P5, B-079)

Одна таблица: заголовок, Markdown, язык (ru/uz/en), статус «Черновик / Опубликовано», кто создал и
кто правил последним (при удалении сотрудника — NULL), время публикации. Черновики видят только те,
кто правит раздел «Настройки · Статьи компании»; опубликованные — все сотрудники.

Revision ID: 5153a46e65f4
Revises: 9362ca08ba13
Create Date: 2026-10-28 11:49:57.210389+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "5153a46e65f4"
down_revision: str | Sequence[str] | None = "9362ca08ba13"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "company_articles",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("language", sa.String(length=2), server_default="ru", nullable=False),
        sa.Column("status", sa.String(length=12), server_default="draft", nullable=False),
        sa.Column("created_by_id", sa.BigInteger(), nullable=True),
        sa.Column("updated_by_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "language IN ('ru', 'uz', 'en')", name=op.f("ck_company_articles_language")
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'published')", name=op.f("ck_company_articles_status")
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name=op.f("fk_company_articles_created_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_id"],
            ["users.id"],
            name=op.f("fk_company_articles_updated_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_company_articles")),
    )
    op.create_index("ix_company_articles_status", "company_articles", ["status", "updated_at"])


def downgrade() -> None:
    op.drop_index("ix_company_articles_status", table_name="company_articles")
    op.drop_table("company_articles")
