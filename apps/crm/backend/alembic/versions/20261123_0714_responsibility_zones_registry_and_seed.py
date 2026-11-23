"""Реестр зон ответственности и девять зон без людей (ЕВ-З, решение владельца 2026-11-23)

* `responsibility_zones` — зона: слаг, названия и описание ru/uz/en, разделы каталога прав,
  ответственный, замещающий, куратор, основание, срок, признак «действует». Журнал — `audit_log`
  (`responsibility_zone.*`);
* данные: девять зон общепринятого набора (`SEED`), людей в них нет — назначает владелец в системе.

Откат: таблица удаляется вместе с зонами и назначениями (журнал `audit_log` остаётся).

Revision ID: 4c04e621fc60
Revises: 7b1e3c9a52d4
Create Date: 2026-11-23 07:14:08.503159+00:00
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "4c04e621fc60"
down_revision: str | Sequence[str] | None = "7b1e3c9a52d4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (код, (ru, uz, en) название, (ru, uz, en) описание, разделы каталога платформы).
# Узбекский — латиница нового алфавита (Ö Ğ Ş Ç, ʼ).
SEED: tuple[tuple[str, tuple[str, str, str], tuple[str, str, str], tuple[str, ...]], ...] = (
    (
        "finance",
        ("Финансы", "Moliya", "Finance"),
        (
            "Счета, оплаты, визы бухгалтера, дебиторка.",
            "Hisoblar, tölovlar, buxgalter vizalari, debitorlik qarzi.",
            "Invoices, payments, accountant visas, receivables.",
        ),
        ("eds.payments", "eds.visa.finance"),
    ),
    (
        "legal",
        ("Право", "Huquq", "Legal"),
        (
            "Визы на договоры, шаблоны, права подписи.",
            "Şartnomalarga vizalar, şablonlar, imzo huquqlari.",
            "Contract visas, templates, signing authority.",
        ),
        ("eds.visa.legal", "eds.signing.manage", "company.settings"),
    ),
    (
        "sales",
        ("Продажи", "Savdo", "Sales"),
        (
            "Заявки, расчёты, КП, обязательства перед клиентом.",
            "Arizalar, hisob-kitoblar, tijorat takliflari, mijoz oldidagi majburiyatlar.",
            "Requests, costings, quotes, commitments to the client.",
        ),
        ("crm.clients", "erp.calc", "eds.drafts"),
    ),
    (
        "first_contact",
        ("Первый контакт", "Birinçi aloqa", "First contact"),
        (
            "Разбор лидов и закрепление за менеджером.",
            "Lidlarni saralaş va menejerga biriktiriş.",
            "Triage of leads and assignment to a manager.",
        ),
        ("crm.leads.triage", "crm.leads", "crm.mail"),
    ),
    (
        "records",
        ("Делопроизводство", "Iş yuritiş", "Records management"),
        (
            "Регистрация, номера, отправка, архив.",
            "Röyxatga oliş, raqamlar, yuboriş, arxiv.",
            "Registration, numbers, dispatch, archive.",
        ),
        ("eds.inbox", "eds.inbox.register", "eds.drafts"),
    ),
    (
        "supply",
        ("Снабжение", "Taʼminot", "Supply"),
        (
            "Закупки, склад, поставщики.",
            "Xaridlar, ombor, yetkazib beruvçilar.",
            "Purchasing, stock, suppliers.",
        ),
        ("erp.stock", "erp.calc.goods"),
    ),
    (
        "projects",
        ("Проекты", "Loyihalar", "Projects"),
        (
            "Этапы, сроки, проблемные проекты.",
            "Bosqiçlar, muddatlar, muammoli loyihalar.",
            "Stages, deadlines, problem projects.",
        ),
        ("eds.projects", "dashboard.queue"),
    ),
    (
        "people",
        ("Люди", "Odamlar", "People"),
        (
            "Приём, отсутствия, замещение, передача дел.",
            "Qabul qiliş, işda yöqlik, almaştiriş, işlarni topşiriş.",
            "Hiring, absences, substitution, handover of cases.",
        ),
        ("admin",),
    ),
    (
        "it_settings",
        ("ИТ и настройки", "IT va sozlamalar", "IT and settings"),
        (
            "Подключения, копии, доступ, состояние.",
            "Ulanişlar, nusxalar, kiriş huquqi, holat.",
            "Connections, backups, access, health.",
        ),
        ("admin", "company.settings"),
    ),
)


def upgrade() -> None:
    op.create_table(
        "responsibility_zones",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("name_ru", sa.String(length=120), nullable=False),
        sa.Column("name_uz", sa.String(length=120), nullable=False),
        sa.Column("name_en", sa.String(length=120), nullable=False),
        sa.Column("description_ru", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("description_uz", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("description_en", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column(
            "sections",
            sa.dialects.postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("responsible_user_id", sa.BigInteger(), nullable=True),
        sa.Column("deputy_user_id", sa.BigInteger(), nullable=True),
        sa.Column("curator_user_id", sa.BigInteger(), nullable=True),
        sa.Column("basis", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("valid_from", sa.Date(), nullable=True),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column("updated_by", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "jsonb_typeof(sections) = 'array'", name=op.f("ck_responsibility_zones_sections")
        ),
        sa.CheckConstraint(
            "valid_from IS NULL OR valid_to IS NULL OR valid_from <= valid_to",
            name=op.f("ck_responsibility_zones_term"),
        ),
        sa.ForeignKeyConstraint(
            ["responsible_user_id"], ["users.id"],
            name=op.f("fk_responsibility_zones_responsible_user_id_users"), ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["deputy_user_id"], ["users.id"],
            name=op.f("fk_responsibility_zones_deputy_user_id_users"), ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["curator_user_id"], ["users.id"],
            name=op.f("fk_responsibility_zones_curator_user_id_users"), ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"],
            name=op.f("fk_responsibility_zones_created_by_users"), ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"], ["users.id"],
            name=op.f("fk_responsibility_zones_updated_by_users"), ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_responsibility_zones")),
        sa.UniqueConstraint("code", name=op.f("uq_responsibility_zones_code")),
    )  # fmt: skip
    for column in ("responsible_user_id", "deputy_user_id", "curator_user_id"):
        op.create_index(op.f(f"ix_responsibility_zones_{column}"), "responsibility_zones", [column])
    op.execute(
        "CREATE TRIGGER trg_responsibility_zones_updated_at BEFORE UPDATE ON responsibility_zones "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
    )
    insert = sa.text(
        "INSERT INTO responsibility_zones (code, name_ru, name_uz, name_en, description_ru, "
        "description_uz, description_en, sections) VALUES (:code, :n_ru, :n_uz, :n_en, :d_ru, "
        ":d_uz, :d_en, CAST(:sections AS jsonb)) ON CONFLICT (code) DO NOTHING"
    )
    for code, names, descriptions, sections in SEED:
        op.get_bind().execute(
            insert,
            {
                "code": code,
                "n_ru": names[0],
                "n_uz": names[1],
                "n_en": names[2],
                "d_ru": descriptions[0],
                "d_uz": descriptions[1],
                "d_en": descriptions[2],
                "sections": json.dumps(sections),
            },
        )


def downgrade() -> None:
    op.drop_table("responsibility_zones")
