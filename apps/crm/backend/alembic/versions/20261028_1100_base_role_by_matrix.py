"""Базовая роль CRM сотрудников с ролями Платформы — по матрице, а не по коду роли (D1-8, B-014)

Базовая роль `admin|manager|viewer` — признак (последний администратор, кого назначить на лида,
замещающий), прав она не даёт. Раньше роль с кодом версии 1 задавала признак по коду: шаблон
«Бухгалтер» без раздела `crm.leads` был `manager` и попадал в «кому передать лида». Теперь признак
вычисляется по матрице ролей: `admin: full` — admin, `crm.leads: full` — manager, иначе viewer
(`app/domain/platform_roles.role_crm_base`). Миграция приводит сохранённые роли сотрудников с ролями
Платформы к этому правилу; сотрудники без ролей Платформы (старый вход) не затрагиваются. Права
ERP (провижининг по матрице) и права CRM (правила `pr:<id>`) не меняются.

Откат возвращает признак `manager` держателям шаблона «Бухгалтер» (как в версии 1).

Revision ID: 0044_base_role_by_matrix
Revises: 0043_messages_bot_created_idx
Create Date: 2026-10-28 11:00:00+00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0044_base_role_by_matrix"
down_revision: str | None = "0043_messages_bot_created_idx"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Нужный признак каждого сотрудника с ролями Платформы: максимум по его ролям.
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


def upgrade() -> None:
    op.execute(_WANTED)
    op.execute(
        """
        DELETE FROM user_roles ur
        USING _wanted_base_role w, roles r
        WHERE ur.user_id = w.user_id AND r.id = ur.role_id AND r.name <> w.name
        """
    )
    op.execute(
        """
        INSERT INTO user_roles (user_id, role_id)
        SELECT w.user_id, r.id FROM _wanted_base_role w JOIN roles r ON r.name = w.name
        ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE user_roles ur SET role_id = manager.id
        FROM roles viewer, roles manager
        WHERE viewer.name = 'viewer' AND manager.name = 'manager' AND ur.role_id = viewer.id
          AND ur.user_id IN (
            SELECT upr.user_id FROM user_platform_roles upr
            JOIN platform_roles pr ON pr.id = upr.role_id WHERE pr.code = 'tpl:ACCOUNTANT'
          )
        """
    )
