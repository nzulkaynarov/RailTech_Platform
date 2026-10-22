"""platform_roles.version и директор без лидов (R-1b, ADR-0012 п. 2)

Что делает:
- добавляет `platform_roles.version` (оптимистическая блокировка: растёт при каждом изменении
  роли, `PATCH /platform-roles/{id}` присылает прочитанную версию, расхождение — 409
  `role_version_conflict`); у существующих ролей — 1;
- системной роли «Директор» (`DIRECTOR`) ставит `crm.leads: read` и `chats.external: read`
  (раньше `full`): директор видит воронку и переписку, но не берёт лиды и не отвечает клиентам;
  версия роли растёт;
- держателям роли «Директор» с доступом к ERP ставит в очередь `erp_provision_user` (права ERP
  пересчитываются по новой матрице). Политики casbin `pr:<id>` приложение сверяет с таблицей
  при старте (`sync_policies`); данных прода нет, пересчёт простой.

Revision ID: 0037_platform_role_version
Revises: 0036_drop_user_platform_roles
Create Date: 2026-10-23 11:00:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0037_platform_role_version"
down_revision: str | None = "0036_drop_user_platform_roles"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DIRECTOR_READ = """
UPDATE platform_roles
SET access = access || '{"crm.leads": "read", "chats.external": "read"}'::jsonb,
    version = version + 1
WHERE code = 'DIRECTOR'
"""
_DIRECTOR_FULL = """
UPDATE platform_roles
SET access = access || '{"crm.leads": "full", "chats.external": "full"}'::jsonb,
    version = version + 1
WHERE code = 'DIRECTOR'
"""
_HOLDERS = """
SELECT u.id FROM users u
JOIN user_platform_roles up ON up.user_id = u.id
JOIN platform_roles r ON r.id = up.role_id
WHERE r.code = 'DIRECTOR' AND u.is_active AND u.platform_access ? 'erp'
ORDER BY u.id
"""


def _recompute_holders() -> None:
    conn = op.get_bind()
    for (user_id,) in conn.execute(sa.text(_HOLDERS)).all():
        conn.execute(
            sa.text(
                "SELECT procrastinate_defer_jobs_v1(ARRAY[ROW('notify', 'erp_provision_user', "
                "0, :lock, NULL, CAST(:args AS jsonb), NULL)::procrastinate_job_to_defer_v1])"
            ),
            {"lock": f"erp_user:{user_id}", "args": f'{{"user_id": {user_id}}}'},
        )


def upgrade() -> None:
    op.add_column(
        "platform_roles",
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
    )
    op.execute(_DIRECTOR_READ)
    _recompute_holders()


def downgrade() -> None:
    op.execute(_DIRECTOR_FULL)
    _recompute_holders()
    op.drop_column("platform_roles", "version")
