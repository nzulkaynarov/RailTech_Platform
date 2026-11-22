"""users.erp_provisioned_at: факт «доступ в ERP выдан» (СЦ-8, статус = факт).

Время последнего успешного ответа ERP на провижининг (`erp_user_id` получен); успешный отзыв
сессий обнуляет. Статус «ок» в карточке сотрудника выводится из этого факта, а не из «в очереди
ничего нет».

Заполнение прежних строк не зависит от порядка выкладки: у активных с доступом к ERP и без
ошибки синхронизации — `now()` (прежнее правило, чтобы карточки не стали красными до старта
воркера); отпечаток каталога `erp_permissions` удаляется, и воркер при следующем старте заново
провижинит всех и запишет настоящий факт (успех — `now()`, сбой — ошибка).

Downgrade удаляет колонку; отпечаток не возвращается (воркер запишет его сам).

Revision ID: 061f7a08104a
Revises: 9b1daa0b361e
Create Date: 2026-11-21 22:45:37.500524+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "061f7a08104a"
down_revision: str | Sequence[str] | None = "9b1daa0b361e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users", sa.Column("erp_provisioned_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.execute(
        "UPDATE users SET erp_provisioned_at = now() "
        "WHERE is_active AND erp_sync_error IS NULL "
        "AND platform_access @> '[\"erp\"]'::jsonb"
    )
    op.execute("DELETE FROM identity_catalog_state WHERE key = 'erp_permissions'")


def downgrade() -> None:
    op.drop_column("users", "erp_provisioned_at")
