"""init: схема Procrastinate

Первая миграция (волна 12, E2): пустая база с таблицами очереди. Схема Procrastinate — зафиксированный
снимок `schema.sql` версии 3.10.0 (как в CRM, ADR-0006). При обновлении Procrastinate новые SQL-миграции из
пакета применяются отдельной ревизией Alembic, этот файл не меняется.

Revision ID: 0001_init
Revises:
Create Date: 2026-10-26 10:00:00+00:00
"""

from collections.abc import Sequence
from pathlib import Path

from alembic import op

revision: str = "0001_init"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PROCRASTINATE_SCHEMA = Path(__file__).parent.parent / "sql" / "procrastinate_3.10.0_schema.sql"

PROCRASTINATE_TABLES = (
    "procrastinate_events",
    "procrastinate_periodic_defers",
    "procrastinate_jobs",
    "procrastinate_workers",
)
PROCRASTINATE_TYPES = (
    "procrastinate_job_to_defer_v1",
    "procrastinate_job_event_type",
    "procrastinate_job_status",
)


def upgrade() -> None:
    # exec_driver_sql: SQL уходит в psycopg без разбора `:param` SQLAlchemy;
    # `%` экранируется, как в procrastinate.schema.SchemaManager.apply_schema.
    schema_sql = PROCRASTINATE_SCHEMA.read_text(encoding="utf-8")
    op.get_bind().exec_driver_sql(schema_sql.replace("%", "%%"))


def downgrade() -> None:
    for table in PROCRASTINATE_TABLES:
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
    op.execute(
        """
        DO $$
        DECLARE fn regprocedure;
        BEGIN
            FOR fn IN
                SELECT p.oid::regprocedure FROM pg_proc p
                JOIN pg_namespace n ON n.oid = p.pronamespace
                WHERE n.nspname = current_schema() AND p.proname LIKE 'procrastinate\\_%'
            LOOP
                EXECUTE 'DROP ROUTINE ' || fn;
            END LOOP;
        END $$;
        """
    )
    for type_name in PROCRASTINATE_TYPES:
        op.execute(f"DROP TYPE IF EXISTS {type_name}")
