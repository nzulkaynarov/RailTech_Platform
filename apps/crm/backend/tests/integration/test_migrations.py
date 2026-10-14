"""Первая миграция применяется, откатывается и применяется повторно."""

import psycopg
from alembic import command
from alembic.config import Config

from app.config import Settings

OBJECTS_SQL = """
SELECT
  (SELECT count(*) FROM pg_tables WHERE tablename LIKE 'procrastinate%%'),
  (SELECT count(*) FROM pg_proc WHERE proname LIKE 'procrastinate%%'),
  (SELECT count(*) FROM pg_type WHERE typname LIKE 'procrastinate%%'),
  (SELECT count(*) FROM pg_extension WHERE extname = 'vector'),
  (SELECT count(*) FROM pg_tables WHERE tablename = 'email_log'),
  (SELECT count(*) FROM pg_tables WHERE tablename LIKE 'external_service_%%')
"""


def count_objects(settings: Settings) -> tuple[int, int, int, int, int, int]:
    with psycopg.connect(settings.libpq_dsn) as conn:
        row = conn.execute(OBJECTS_SQL).fetchone()
    assert row is not None
    return row


def test_upgrade_downgrade_upgrade(alembic_config: Config, live_settings: Settings) -> None:
    command.upgrade(alembic_config, "head")
    tables, functions, types, vector, email_log, external = count_objects(live_settings)
    assert (tables, vector, email_log) == (4, 1, 1)  # email_log — M3-CRM-08
    assert external == 3  # проверки, инциденты, выключатели — M3-CRM-12
    assert functions > 0
    assert types > 0

    command.downgrade(alembic_config, "base")
    assert count_objects(live_settings) == (0, 0, 0, 0, 0, 0)

    command.upgrade(alembic_config, "head")
    assert count_objects(live_settings)[0] == 4
