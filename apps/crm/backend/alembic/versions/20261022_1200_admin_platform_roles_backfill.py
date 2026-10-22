"""users: активным администраторам CRM без ролей Платформы — platform_roles = ["ADMIN"] (CRM-01b)

Миграция 0032 добавила `platform_roles` пустым: администратор, созданный через `/setup` до CRM-01,
после выхода Платформы получил бы 403 `NO_PLATFORM_ROLE` и не смог бы выдать роли никому, включая
себя. Правило CRM-01 — непустые роли вычисляют доступ: `ADMIN` -> роль CRM `admin`, доступ
`["crm", "erp"]` (как у первого администратора из `/setup` теперь), роль ERP `admin`
(суперпользователь, `role_codes` ERP игнорирует).

Что делает: для активных пользователей с ролью `admin` и пустыми `platform_roles` ставит
`["ADMIN"]` и добавляет `"erp"` в `platform_access`; у кого ERP не было — ставит в очередь
Procrastinate задачу `erp_provision_user` (как выдача доступа), пишет аудит `user.update`
от системы. `erp_role_codes` не трогает (для `admin` ERP их игнорирует; следующее изменение
пользователя пересчитает). Идемпотентна: затрагивает только строки с пустыми `platform_roles`.
Неактивных администраторов, не-администраторов и пользователей с уже заданными ролями не меняет.
Downgrade — no-op: вернуть «пусто» нельзя отличить от ролей, выданных вручную.

Revision ID: 0033_admin_platform_roles
Revises: 0032_user_platform_roles
Create Date: 2026-10-22 12:00:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0033_admin_platform_roles"
down_revision: str | None = "0032_user_platform_roles"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Активные администраторы без ролей Платформы; `FOR UPDATE` — на время миграции.
_TARGETS = """
SELECT u.id, u.platform_access ? 'erp' AS had_erp
FROM users u
WHERE u.is_active
  AND u.platform_roles = '[]'::jsonb
  AND EXISTS (
      SELECT 1 FROM user_roles ur JOIN roles r ON r.id = ur.role_id
      WHERE ur.user_id = u.id AND r.name = 'admin'
  )
ORDER BY u.id
FOR UPDATE OF u
"""


def upgrade() -> None:
    conn = op.get_bind()
    targets = conn.execute(sa.text(_TARGETS)).all()
    for user_id, had_erp in targets:
        conn.execute(
            sa.text(
                "UPDATE users SET platform_roles = '[\"ADMIN\"]'::jsonb, "
                'platform_access = \'["crm", "erp"]\'::jsonb WHERE id = :id'
            ),
            {"id": user_id},
        )
        conn.execute(
            sa.text(
                "INSERT INTO audit_log (actor_type, action, entity_type, entity_id, before, after) "
                "VALUES ('system', 'user.update', 'user', :entity, "
                "CAST(:before AS jsonb), CAST(:after AS jsonb))"
            ),
            {
                "entity": str(user_id),
                "before": '{"platform_roles": [], "platform_access_erp": %s}'
                % ("true" if had_erp else "false"),
                "after": '{"platform_roles": ["ADMIN"], "platform_access_erp": true}',
            },
        )
        if not had_erp:
            conn.execute(
                sa.text(
                    "SELECT procrastinate_defer_jobs_v1(ARRAY[ROW('notify', 'erp_provision_user', "
                    "0, :lock, NULL, CAST(:args AS jsonb), NULL)::procrastinate_job_to_defer_v1])"
                ),
                {"lock": f"erp_user:{user_id}", "args": f'{{"user_id": {user_id}}}'},
            )


def downgrade() -> None:
    """No-op: проставленные роли неотличимы от выданных вручную."""
