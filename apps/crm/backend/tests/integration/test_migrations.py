"""Первая миграция применяется, откатывается и применяется повторно."""

import psycopg
import pytest
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


HANDOFF_COLUMNS_SQL = """
SELECT column_name FROM information_schema.columns
WHERE table_name = 'clients' AND column_name LIKE 'erp_handoff%%' ORDER BY column_name
"""


def test_client_handoff_columns_come_and_go_with_the_revision(
    alembic_config: Config, live_settings: Settings
) -> None:
    """FIX-31: состояние передачи клиента в ERP — три колонки; downgrade их снимает."""
    command.upgrade(alembic_config, "head")
    with psycopg.connect(live_settings.libpq_dsn) as conn:
        columns = [r[0] for r in conn.execute(HANDOFF_COLUMNS_SQL).fetchall()]
    assert columns == ["erp_handoff_error", "erp_handoff_request", "erp_handoff_status"]

    command.downgrade(alembic_config, "0026_user_platform_access")
    with psycopg.connect(live_settings.libpq_dsn) as conn:
        assert conn.execute(HANDOFF_COLUMNS_SQL).fetchall() == []

    command.upgrade(alembic_config, "head")
    with psycopg.connect(live_settings.libpq_dsn) as conn:
        assert len(conn.execute(HANDOFF_COLUMNS_SQL).fetchall()) == 3


def test_webhook_reliability_revision_dedupes_erp_deal_ids_and_is_reversible(
    alembic_config: Config, live_settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    """FIX-33: дубли `erp_deal_id` сворачиваются при upgrade (остаётся зеркало с лидом, затем самое
    раннее), дальше значение уникально; downgrade возвращает обычный индекс и убирает колонки."""
    command.upgrade(alembic_config, "head")
    command.downgrade(alembic_config, "0027_client_erp_handoff")
    with psycopg.connect(live_settings.libpq_dsn, autocommit=True) as conn:
        conn.execute("TRUNCATE deals, leads, erp_incoming_events RESTART IDENTITY CASCADE")
        lead_id = conn.execute(
            "INSERT INTO leads (display_name) VALUES ('Лид') RETURNING id"
        ).fetchone()[0]  # type: ignore[index]
        conn.execute(
            "INSERT INTO deals (title, erp_deal_id, external_stage) VALUES "
            "('первое без лида', 500, 'request'), "
            "('второе с лидом', 500, 'paid'), "
            "('третье без лида', 500, 'paid'), "
            "('одиночное', 501, 'request'), "
            "('локальное', NULL, NULL)"
        )
        conn.execute("UPDATE deals SET lead_id = %s WHERE title = 'второе с лидом'", (lead_id,))
        conn.execute(
            "INSERT INTO erp_incoming_events (event_id, event_type, erp_company_id, crm_client_id, "
            "payload) VALUES ('e-1', 'quote.sent', 1, 1, '{}')"
        )

    with caplog.at_level("INFO", logger="alembic.runtime.migration"):
        command.upgrade(alembic_config, "head")
    assert "collapsed 2 duplicate deals.erp_deal_id" in caplog.text
    with psycopg.connect(live_settings.libpq_dsn, autocommit=True) as conn:
        rows = conn.execute(
            "SELECT title, erp_deal_id, external_stage FROM deals ORDER BY id"
        ).fetchall()
        assert rows == [
            ("первое без лида", None, None),
            ("второе с лидом", 500, "paid"),
            ("третье без лида", None, None),
            ("одиночное", 501, "request"),
            ("локальное", None, None),
        ]
        with pytest.raises(psycopg.errors.UniqueViolation):
            conn.execute("INSERT INTO deals (title, erp_deal_id) VALUES ('дубль', 501)")
        conn.execute("INSERT INTO deals (title) VALUES ('ещё локальное')")  # NULL не конфликтует
        conn.execute(
            "INSERT INTO erp_incoming_events (event_id, event_type, status, error, payload) VALUES "
            "('e-2', 'warehouse.exploded', 'rejected', 'unknown', '{}')"
        )

    command.downgrade(alembic_config, "0027_client_erp_handoff")
    with psycopg.connect(live_settings.libpq_dsn, autocommit=True) as conn:
        index = conn.execute(
            "SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_deals_erp_deal_id'"
        ).fetchone()
        assert index is not None
        assert "UNIQUE" not in index[0]
        columns = {
            r[0]
            for r in conn.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name IN ('deals', 'erp_incoming_events')"
            ).fetchall()
        }
        assert not columns & {"external_stage_at", "attempts", "outbox", "notified_at"}
        events = conn.execute("SELECT event_id FROM erp_incoming_events").fetchall()
        assert events == [("e-1",)], (
            "отклонённое событие в старой схеме невозможно и не переносится"
        )

    command.upgrade(alembic_config, "head")
