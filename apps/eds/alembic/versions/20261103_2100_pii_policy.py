"""Политика защиты данных для ИИ (PD-BIZ): проекция из CRM и сканы по умолчанию включены

`docflow_settings.pii_policy` — проекция настройки CRM `ai.pii_policy` (событие `crm.ai_policy.changed`): `business`
(«Деловая») или `strict`; `pii_policy_at` — момент изменения в CRM (старое событие не применяется). Пока
`pii_policy_at` пуст (событие не приходило), код ведёт себя как «Строгая»; колонка по умолчанию `business` — значение
до первого события.
`recognize_scans` по решению владельца 2026-11-03 включён по умолчанию (при «Строгой» сканы всё равно не читаются):
строка, которую администратор не менял (`updated_by IS NULL` — посев первой миграции), переводится в «включено»,
выбор администратора сохраняется. Downgrade возвращает «выключено» тем же строкам и убирает колонки.

Revision ID: 7f181c0c14fa
Revises: 714ca7e43a9c
Create Date: 2026-11-07 10:00:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "7f181c0c14fa"
down_revision: str | Sequence[str] | None = "714ca7e43a9c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "docflow_settings",
        sa.Column("pii_policy", sa.String(length=16), server_default="business", nullable=False),
    )
    op.add_column("docflow_settings", sa.Column("pii_policy_at", sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint(
        op.f("ck_docflow_settings_pii_policy"), "docflow_settings", "pii_policy IN ('business', 'strict')"
    )
    op.alter_column("docflow_settings", "recognize_scans", server_default=sa.text("true"))
    op.execute("UPDATE docflow_settings SET recognize_scans = true WHERE updated_by IS NULL")


def downgrade() -> None:
    op.execute("UPDATE docflow_settings SET recognize_scans = false WHERE updated_by IS NULL")
    op.alter_column("docflow_settings", "recognize_scans", server_default=sa.text("false"))
    op.drop_constraint(op.f("ck_docflow_settings_pii_policy"), "docflow_settings", type_="check")
    op.drop_column("docflow_settings", "pii_policy_at")
    op.drop_column("docflow_settings", "pii_policy")
