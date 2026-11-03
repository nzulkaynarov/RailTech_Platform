"""Типы входящих писем как справочник и правила отправителя (MAIL-TYPES)

* `mail_types` — справочник: код, название ru/uz/en, цвет и значок из закрытого набора, действие по
  умолчанию из закрытого списка кода, «действует», порядок; стартовый набор из восьми типов (можно
  править и отключать);
* `mail_sender_rules` — «отправитель или домен → тип», один шаблон — одно правило;
* `inbound_mail.type_code` и `type_source` (`rule | ai | manual`); старые подсказки помощника
  переносятся в тип: покупатель → «Запрос клиента», официальное → «Официальное письмо», документ
  поставщика → «Счёт поставщика», «прочее» остаётся без типа;
* итог письма `price` («прайс загружен»); `assist_action` шире — туда пишется код действия по
  умолчанию типа.

Откат: итог `price` становится «в архив» с причиной, действие подсказки возвращается к трём
прежним словам (остальное стирается), таблицы и колонки удаляются.

Revision ID: 97bc02846729
Revises: 76abc53006ad
Create Date: 2026-11-03 16:08:04.502778+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "97bc02846729"
down_revision: str | Sequence[str] | None = "76abc53006ad"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ACTIONS = (
    "'register_incoming', 'create_lead', 'supplier_price', 'to_accountant', "
    "'archive_mailing', 'reply_template', 'suspicious'"
)
_COLORS = "'blue', 'green', 'gold', 'red', 'purple', 'cyan', 'default'"
_ICONS = "'mail', 'team', 'calendar', 'file', 'wallet', 'bank', 'notification', 'stop'"
_OUTCOME_OLD = "outcome IS NULL OR outcome IN ('registered', 'lead', 'replied', 'archived')"
_OUTCOME_NEW = (
    "outcome IS NULL OR outcome IN ('registered', 'lead', 'replied', 'archived', 'price')"
)
_OLD_ACTIONS = "'register', 'lead', 'archive'"

# code, ru, uz, en, color, icon, action
_SEED: tuple[tuple[str, str, str, str, str, str, str], ...] = (
    (
        "client_request",
        "Запрос клиента",
        "Mijoz so'rovi",
        "Customer request",
        "green",
        "mail",
        "create_lead",
    ),
    (
        "cooperation",
        "Предложение о сотрудничестве",
        "Hamkorlik taklifi",
        "Partnership offer",
        "purple",
        "team",
        "register_incoming",
    ),
    (
        "meeting",
        "Приглашение на встречу",
        "Uchrashuvga taklif",
        "Meeting invitation",
        "cyan",
        "calendar",
        "reply_template",
    ),
    (
        "supplier_price",
        "КП или прайс поставщика",
        "Yetkazib beruvchi narxnomasi",
        "Supplier quote or price list",
        "blue",
        "file",
        "supplier_price",
    ),
    (
        "supplier_invoice",
        "Счёт поставщика",
        "Yetkazib beruvchi hisobi",
        "Supplier invoice",
        "gold",
        "wallet",
        "to_accountant",
    ),
    (
        "official",
        "Официальное письмо (госорган, банк, налоговая)",
        "Rasmiy xat (davlat organi, bank, soliq)",
        "Official letter (authority, bank, tax)",
        "red",
        "bank",
        "register_incoming",
    ),
    (
        "mailing",
        "Рассылка",
        "Reklama xabarnomasi",
        "Newsletter",
        "default",
        "notification",
        "archive_mailing",
    ),
    ("spam", "Спам", "Spam", "Spam", "default", "stop", "suspicious"),
)


def upgrade() -> None:
    op.create_table(
        "mail_types",
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("name_ru", sa.String(length=120), nullable=False),
        sa.Column("name_uz", sa.String(length=120), server_default="", nullable=False),
        sa.Column("name_en", sa.String(length=120), server_default="", nullable=False),
        sa.Column("color", sa.String(length=16), server_default="default", nullable=False),
        sa.Column("icon", sa.String(length=16), server_default="mail", nullable=False),
        sa.Column("default_action", sa.String(length=24), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("position", sa.Integer(), server_default="0", nullable=False),
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
            f"default_action IN ({_ACTIONS})", name=op.f("ck_mail_types_default_action")
        ),
        sa.CheckConstraint(f"color IN ({_COLORS})", name=op.f("ck_mail_types_color")),
        sa.CheckConstraint(f"icon IN ({_ICONS})", name=op.f("ck_mail_types_icon")),
        sa.PrimaryKeyConstraint("code", name=op.f("pk_mail_types")),
    )
    op.create_index("ix_mail_types_position", "mail_types", ["position"])
    op.execute(
        "CREATE TRIGGER trg_mail_types_updated_at BEFORE UPDATE ON mail_types "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
    )
    table = sa.table(
        "mail_types",
        sa.column("code", sa.String),
        sa.column("name_ru", sa.String),
        sa.column("name_uz", sa.String),
        sa.column("name_en", sa.String),
        sa.column("color", sa.String),
        sa.column("icon", sa.String),
        sa.column("default_action", sa.String),
        sa.column("position", sa.Integer),
    )
    op.bulk_insert(
        table,
        [
            {
                "code": code,
                "name_ru": ru,
                "name_uz": uz,
                "name_en": en,
                "color": color,
                "icon": icon,
                "default_action": action,
                "position": (index + 1) * 10,
            }
            for index, (code, ru, uz, en, color, icon, action) in enumerate(_SEED)
        ],
    )

    op.create_table(
        "mail_sender_rules",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("pattern", sa.String(length=255), nullable=False),
        sa.Column("type_code", sa.String(length=32), nullable=False),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["type_code"],
            ["mail_types.code"],
            name=op.f("fk_mail_sender_rules_type_code_mail_types"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_mail_sender_rules_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_mail_sender_rules")),
    )
    op.create_index("uq_mail_sender_rules_pattern", "mail_sender_rules", ["pattern"], unique=True)

    table_name = "inbound_mail"
    op.add_column(table_name, sa.Column("type_code", sa.String(length=32), nullable=True))
    op.add_column(table_name, sa.Column("type_source", sa.String(length=8), nullable=True))
    op.create_check_constraint(
        op.f("ck_inbound_mail_type_source"),
        table_name,
        "type_source IS NULL OR type_source IN ('rule', 'ai', 'manual')",
    )
    op.create_index("ix_inbound_mail_type_code", table_name, ["type_code"])
    op.alter_column(table_name, "assist_action", type_=sa.String(length=32), existing_nullable=True)
    op.drop_constraint(op.f("ck_inbound_mail_outcome"), table_name, type_="check")
    op.create_check_constraint(op.f("ck_inbound_mail_outcome"), table_name, _OUTCOME_NEW)
    op.execute(
        "UPDATE inbound_mail SET type_code = CASE assist_kind "
        "WHEN 'buyer' THEN 'client_request' WHEN 'official' THEN 'official' "
        "WHEN 'supplier_doc' THEN 'supplier_invoice' END, type_source = 'ai' "
        "WHERE assist_status = 'done' AND assist_kind IN ('buyer', 'official', 'supplier_doc')"
    )


def downgrade() -> None:
    table_name = "inbound_mail"
    op.execute(
        "UPDATE inbound_mail SET outcome = 'archived', archive_reason = 'Прайс загружен' "
        "WHERE outcome = 'price'"
    )
    op.drop_constraint(op.f("ck_inbound_mail_outcome"), table_name, type_="check")
    op.create_check_constraint(op.f("ck_inbound_mail_outcome"), table_name, _OUTCOME_OLD)
    op.execute(
        "UPDATE inbound_mail SET assist_action = CASE assist_action "
        "WHEN 'create_lead' THEN 'lead' WHEN 'register_incoming' THEN 'register' "
        "WHEN 'archive_mailing' THEN 'archive' ELSE assist_action END"
    )
    op.execute(
        f"UPDATE inbound_mail SET assist_action = NULL WHERE assist_action NOT IN ({_OLD_ACTIONS})"
    )
    op.alter_column(table_name, "assist_action", type_=sa.String(length=16), existing_nullable=True)
    op.drop_index("ix_inbound_mail_type_code", table_name=table_name)
    op.drop_constraint(op.f("ck_inbound_mail_type_source"), table_name, type_="check")
    op.drop_column(table_name, "type_source")
    op.drop_column(table_name, "type_code")
    op.drop_index("uq_mail_sender_rules_pattern", table_name="mail_sender_rules")
    op.drop_table("mail_sender_rules")
    op.execute("DROP TRIGGER IF EXISTS trg_mail_types_updated_at ON mail_types")
    op.drop_index("ix_mail_types_position", table_name="mail_types")
    op.drop_table("mail_types")
