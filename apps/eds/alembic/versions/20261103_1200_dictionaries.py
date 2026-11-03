"""Справочники документооборота как данные (EDS-REG, шаг В1/4 карты жизненного цикла)

Таблица `dictionary_items` — значения справочников EDS (вид, код, название ru/uz/en, поля вида, «действует», порядок).
Засевается текущими значениями кода: виды входящих документов (были `services/letter_kinds.py`) и способы
получения (были перечнем и CHECK у `letters.receipt_method`). CHECK по способу получения снят, колонка расширена до 32
знаков; коды те же — старые письма не меняются. Downgrade: удаляет таблицу, возвращает CHECK и длину; письма со
способом не из стартового набора теряют способ (`NULL`) — иначе CHECK не вернуть.

Revision ID: e2bd0879b468
Revises: 983e0473b753
Create Date: 2026-11-03 12:00:00+00:00
"""

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e2bd0879b468"
down_revision: str | Sequence[str] | None = "983e0473b753"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STARTER_METHODS = ("post", "paper", "taxpayer_cabinet", "courier", "email")

# (код, ru, uz, en, attrs) — значения на момент миграции; дальше их ведёт администратор.
LETTER_KINDS = (
    (
        "tax_notice",
        "Требование или уведомление ГНК",
        "Soliq qo‘mitasi talabnomasi yoki xabarnomasi",
        "Tax authority demand or notice",
        {"urgent": True, "due_days": 3},
    ),
    ("bank", "Письмо банка", "Bank xati", "Bank letter", {"urgent": False, "due_days": None}),
    ("supplier", "Письмо поставщика", "Yetkazib beruvchi xati", "Supplier letter", {"urgent": False, "due_days": None}),
    ("government", "Письмо госоргана", "Davlat organi xati", "Government letter", {"urgent": False, "due_days": None}),
    (
        "counterparty",
        "Письмо контрагента",
        "Kontragent xati",
        "Counterparty letter",
        {"urgent": False, "due_days": None},
    ),
    ("other", "Прочее", "Boshqa", "Other", {"urgent": False, "due_days": None}),
)
# Порядок показа в форме — как был в интерфейсе: бумага, почта, my.soliq, курьер, e-mail.
RECEIPT_METHODS = (
    ("paper", "Бумага (принесли лично)", "Qog‘oz (shaxsan olib kelingan)", "Paper (handed in)"),
    ("post", "Почта", "Pochta", "Post"),
    (
        "taxpayer_cabinet",
        "Кабинет налогоплательщика my.soliq",
        "Soliq to‘lovchi kabineti my.soliq",
        "Taxpayer cabinet my.soliq",
    ),
    ("courier", "Курьер", "Kuryer", "Courier"),
    ("email", "E-mail", "E-mail", "Email"),
)


def upgrade() -> None:
    table = op.create_table(
        "dictionary_items",
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("name_ru", sa.String(length=120), nullable=False),
        sa.Column("name_uz", sa.String(length=120), server_default=sa.text("''"), nullable=False),
        sa.Column("name_en", sa.String(length=120), server_default=sa.text("''"), nullable=False),
        sa.Column(
            "attrs", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("kind", "code", name=op.f("pk_dictionary_items")),
    )
    now = datetime.now(UTC)
    rows = [
        {
            "kind": "letter-kinds",
            "code": code,
            "name_ru": ru,
            "name_uz": uz,
            "name_en": en,
            "attrs": attrs,
            "active": True,
            "position": (index + 1) * 10,
            "created_at": now,
            "updated_at": now,
        }
        for index, (code, ru, uz, en, attrs) in enumerate(LETTER_KINDS)
    ] + [
        {
            "kind": "receipt-methods",
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
        for index, (code, ru, uz, en) in enumerate(RECEIPT_METHODS)
    ]
    op.bulk_insert(table, rows)
    op.drop_constraint(op.f("ck_letters_receipt_method"), "letters", type_="check")
    op.alter_column(
        "letters",
        "receipt_method",
        existing_type=sa.String(length=24),
        type_=sa.String(length=32),
        existing_nullable=True,
    )


def downgrade() -> None:
    starter = ", ".join(f"'{code}'" for code in STARTER_METHODS)
    op.execute(f"UPDATE letters SET receipt_method = NULL WHERE receipt_method NOT IN ({starter})")
    op.alter_column(
        "letters",
        "receipt_method",
        existing_type=sa.String(length=32),
        type_=sa.String(length=24),
        existing_nullable=True,
    )
    op.create_check_constraint(
        op.f("ck_letters_receipt_method"),
        "letters",
        f"receipt_method IS NULL OR receipt_method IN ({starter})",
    )
    op.drop_table("dictionary_items")
