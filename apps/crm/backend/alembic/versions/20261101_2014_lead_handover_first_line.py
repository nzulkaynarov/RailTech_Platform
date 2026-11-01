"""Передача лида первой линией: делопроизводитель → менеджер (D17G-1; DECISIONS 2026-11-01 п. 1)

Что делает:
- `escalations`: кто передал лида (`handed_by_user_id`, бот — NULL) и тип обращения
  (`request_type`) — «Передать менеджеру» дополняет передачу бота запиской (`reason_text`) и
  причиной `handed_over`;
- роли из шаблона «Делопроизводитель» (`tpl:REGISTRAR`, вставлены миграцией P8) с
  `crm.leads: full` переводит на `crm.leads: read` + новый раздел `crm.leads.triage: full`
  (разобрать и передать, без «Забрать» и ответа клиенту). Роль, которую администратор уже
  поменял (`crm.leads` не `full`), не трогается. Версия роли растёт;
- признак базовой роли CRM сотрудников с ролями Платформы пересчитывается по матрице, как в
  `0048_base_role_by_matrix`: делопроизводитель без `crm.leads: full` становится `viewer` (кому
  передать лида — держатели `crm.leads: full`). У остальных признак уже совпадает с матрицей.

Права остальных ролей (менеджер, менеджер-универсал, директор, роли администратора) не меняются.
Политики casbin (`pr:<id>`) приложение сверяет с таблицей ролей при старте; права EDS и ERP
раздел не даёт. Лиды, которые делопроизводитель уже забрал, миграция не передаёт (данных на проде
нет; на живой базе — передать до выкладки).

Downgrade возвращает `crm.leads: full` ролям `tpl:REGISTRAR` с разделом `crm.leads.triage`, снимает
раздел, пересчитывает признак базовой роли и удаляет колонки.

Revision ID: b95ca021f2f0
Revises: bf63b9342895
Create Date: 2026-11-01 20:14:27.285776+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b95ca021f2f0"
down_revision: str | Sequence[str] | None = "bf63b9342895"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TRIAGE = """
UPDATE platform_roles
SET access = access || '{"crm.leads": "read", "crm.leads.triage": "full"}'::jsonb,
    version = version + 1
WHERE code = 'tpl:REGISTRAR' AND access->>'crm.leads' = 'full'
"""
_UNTRIAGE = """
UPDATE platform_roles
SET access = (access - 'crm.leads.triage') || '{"crm.leads": "full"}'::jsonb,
    version = version + 1
WHERE code = 'tpl:REGISTRAR' AND access ? 'crm.leads.triage'
"""
# Признак базовой роли по матрице (правило `domain/platform_roles.role_crm_base`, миграция 0048).
_WANTED = """
CREATE TEMPORARY TABLE _wanted_base_role ON COMMIT DROP AS
SELECT upr.user_id,
       CASE
         WHEN bool_or(pr.access ->> 'admin' = 'full') THEN 'admin'
         WHEN bool_or(pr.access ->> 'crm.leads' = 'full') THEN 'manager'
         ELSE 'viewer'
       END AS name
FROM user_platform_roles upr
JOIN platform_roles pr ON pr.id = upr.role_id
GROUP BY upr.user_id
"""
_DROP_OTHER = """
DELETE FROM user_roles ur
USING _wanted_base_role w, roles r
WHERE ur.user_id = w.user_id AND r.id = ur.role_id AND r.name <> w.name
"""
_ADD_WANTED = """
INSERT INTO user_roles (user_id, role_id)
SELECT w.user_id, r.id FROM _wanted_base_role w JOIN roles r ON r.name = w.name
ON CONFLICT DO NOTHING
"""


def _rebase() -> None:
    op.execute(sa.text("DROP TABLE IF EXISTS _wanted_base_role"))
    op.execute(sa.text(_WANTED))
    op.execute(sa.text(_DROP_OTHER))
    op.execute(sa.text(_ADD_WANTED))
    op.execute(sa.text("DROP TABLE _wanted_base_role"))


def upgrade() -> None:
    op.add_column(
        "escalations",
        sa.Column(
            "handed_by_user_id",
            sa.BigInteger(),
            sa.ForeignKey(
                "users.id",
                ondelete="SET NULL",
                name="fk_escalations_handed_by_user_id_users",
            ),
            nullable=True,
        ),
    )
    op.add_column("escalations", sa.Column("request_type", sa.String(16), nullable=True))
    op.execute(sa.text(_TRIAGE))
    _rebase()


def downgrade() -> None:
    op.execute(sa.text(_UNTRIAGE))
    _rebase()
    op.drop_column("escalations", "request_type")
    op.drop_column("escalations", "handed_by_user_id")
