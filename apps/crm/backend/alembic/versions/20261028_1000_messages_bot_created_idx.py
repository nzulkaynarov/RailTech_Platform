"""messages: частичный индекс ответов бота по времени для строки «Ответы ИИ» (W15-H3c)

Строка `ai_replies` центра внешних сервисов раз в минуту считает ответы бота за окно и ищет
последний сбой и последний успешный ответ за сутки: `WHERE role = 'bot' AND created_at >= ...`.
Без индекса это последовательный просмотр всей `messages` (на 2 млн строк — ~160 мс, с индексом —
доли миллисекунды). Индекс частичный — по строкам бота, клиентские и менеджерские в него не входят.
Создаётся `CONCURRENTLY` вне транзакции, чтобы не блокировать запись в `messages`. Данных для
переноса нет.

Revision ID: 0043_messages_bot_created_idx
Revises: 0042_staff_profile
Create Date: 2026-10-28 10:00:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0043_messages_bot_created_idx"
down_revision: str | None = "0042_staff_profile"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEX = "ix_messages_bot_created_at"


def upgrade() -> None:
    with op.get_context().autocommit_block():
        # Оборванный `CREATE INDEX CONCURRENTLY` оставляет невалидный индекс с тем же именем: он
        # занимает имя, но запросы его не берут. Перед созданием такой остаток убираем.
        broken = op.get_bind().execute(
            sa.text(
                "SELECT 1 FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid "
                "WHERE c.relname = :name AND NOT i.indisvalid"
            ),
            {"name": _INDEX},
        )
        if broken.first() is not None:
            op.drop_index(
                _INDEX, table_name="messages", postgresql_concurrently=True, if_exists=True
            )
        op.create_index(
            _INDEX,
            "messages",
            ["created_at"],
            postgresql_where=sa.text("role = 'bot'"),
            postgresql_concurrently=True,
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.drop_index(
            _INDEX,
            table_name="messages",
            postgresql_concurrently=True,
            if_exists=True,
        )
