"""Одно письмо — один входящий номер (EDS-DUP)

`letters.dedup_key` — ключ точного совпадения «корреспондент (ИНН, иначе название без регистра, кавычек и формы
собственности) + исходящий номер + дата исходящего»; частичный уникальный индекс `uq_letters_dedup_key`
(`WHERE dedup_key IS NOT NULL`): две одновременные регистрации одного письма дают один ВХ. Уже зарегистрированные письма
получают ключ по тем же правилам — только самое раннее из совпадающих (остальные — без ключа: дубли на проде закрывает
делопроизводитель действием «Это дубль»). `letters.duplicate_of_id` — оригинал письма-дубля; статус письма `duplicate`,
статус поручения `cancelled`. Откат: дубли возвращаются в «Ждёт резолюции» (поручения — в «Исполнено»: срок и
напоминания по ним не нужны), снимаются индекс и поля.

Revision ID: 714ca7e43a9c
Revises: b8774e6a6f55
Create Date: 2026-11-03 11:52:14.816519+00:00
"""

import re
import unicodedata
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "714ca7e43a9c"
down_revision: str | Sequence[str] | None = "b8774e6a6f55"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LETTER_OLD = (
    "status IN ('awaiting_resolution', 'resolved', 'returned', 'rejected', 'in_execution', 'executed', 'noted')"
)
_LETTER_NEW = (
    "status IN ('awaiting_resolution', 'resolved', 'returned', 'rejected', 'in_execution', 'executed', 'noted', "
    "'duplicate')"
)
_INSTRUCTION_OLD = "status IN ('in_work', 'executed')"
_INSTRUCTION_NEW = "status IN ('in_work', 'executed', 'cancelled')"

# Копия правил `app/services/letter_dedup.py` на момент ревизии (миграция не зависит от кода приложения).
_LEGAL_FORMS = frozenset(
    {
        "ооо",
        "ooo",
        "000",
        "llc",
        "mchj",
        "мчж",
        "ао",
        "ao",
        "оао",
        "зао",
        "пао",
        "ип",
        "ltd",
        "jsc",
        "inc",
        "aj",
        "аж",
        "хк",
        "xk",
        "чп",
    }
)
_PUNCT = re.compile(r"[«»\"“”„‟'`’‘.,;:()\[\]{}]")


def _name_key(name: str | None) -> str:
    text = unicodedata.normalize("NFKC", name or "").casefold().replace("ё", "е")
    return " ".join(word for word in _PUNCT.sub(" ", text).split() if word not in _LEGAL_FORMS)


_NO_NUMBER = frozenset({"бн", "bn", "нет", "безномера", "безномер", "бномера", "nn", "нн", "none", "na"})


def _ref_key(ref: str | None) -> str:
    text = unicodedata.normalize("NFKC", re.sub(r"[№#]", "", ref or "")).casefold().replace("ё", "е")
    key = re.sub(r"\s", "", text)
    bare = re.sub(r"[\W_]", "", key)
    return "" if not bare or bare in _NO_NUMBER else key


def _exact_key(inn: str | None, name: str | None, client: int | None, ref: str | None, ref_date: object) -> str | None:
    number = _ref_key(ref)
    if not number or ref_date is None:
        return None
    if inn:
        sender = f"i:{inn}"
    elif _name_key(name):
        sender = f"n:{_name_key(name)}"
    elif client is not None:
        sender = f"c:{client}"
    else:
        return None
    return f"{number}|{ref_date}|{sender}"[:400]


def upgrade() -> None:
    op.add_column("letters", sa.Column("dedup_key", sa.String(length=400), nullable=True))
    op.add_column("letters", sa.Column("duplicate_of_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_letters_duplicate_of_id_letters"),
        "letters",
        "letters",
        ["duplicate_of_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.drop_constraint(op.f("ck_letters_status"), "letters", type_="check")
    op.create_check_constraint(op.f("ck_letters_status"), "letters", _LETTER_NEW)
    op.drop_constraint(op.f("ck_instructions_status"), "instructions", type_="check")
    op.create_check_constraint(op.f("ck_instructions_status"), "instructions", _INSTRUCTION_NEW)

    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT id, sender_inn, sender_name, crm_client_id, sender_ref_number, sender_ref_date FROM letters "
            "WHERE sender_ref_number IS NOT NULL AND sender_ref_date IS NOT NULL ORDER BY registered_at, id"
        )
    ).all()
    taken: set[str] = set()
    for row in rows:
        key = _exact_key(row.sender_inn, row.sender_name, row.crm_client_id, row.sender_ref_number, row.sender_ref_date)
        if key is None or key in taken:
            continue
        taken.add(key)
        bind.execute(sa.text("UPDATE letters SET dedup_key = :key WHERE id = :id"), {"key": key, "id": row.id})
    op.create_index(
        "uq_letters_dedup_key",
        "letters",
        ["dedup_key"],
        unique=True,
        postgresql_where=sa.text("dedup_key IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_letters_dedup_key", table_name="letters")
    op.drop_constraint(op.f("ck_instructions_status"), "instructions", type_="check")
    op.execute("UPDATE instructions SET status = 'executed' WHERE status = 'cancelled'")
    op.create_check_constraint(op.f("ck_instructions_status"), "instructions", _INSTRUCTION_OLD)
    op.drop_constraint(op.f("ck_letters_status"), "letters", type_="check")
    op.execute("UPDATE letters SET status = 'awaiting_resolution' WHERE status = 'duplicate'")
    op.create_check_constraint(op.f("ck_letters_status"), "letters", _LETTER_OLD)
    op.drop_constraint(op.f("fk_letters_duplicate_of_id_letters"), "letters", type_="foreignkey")
    op.drop_column("letters", "duplicate_of_id")
    op.drop_column("letters", "dedup_key")
