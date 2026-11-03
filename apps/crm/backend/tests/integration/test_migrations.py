"""Первая миграция применяется, откатывается и применяется повторно."""

import psycopg
import pytest
from alembic import command
from alembic.config import Config

from app.config import Settings

#: Последняя ревизия, где ещё есть `erp_incoming_events` (0039 заменяет её таблицами rt_bus).
SEAM_REVISION = "0029_erp_seam_hardening"

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
        command.upgrade(alembic_config, SEAM_REVISION)
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


def test_seam_hardening_revision_is_reversible(
    alembic_config: Config, live_settings: Settings
) -> None:
    """FIX-35: `documents.erp_document_id` (уникален в паре с клиентом), статус `skipped`,
    `body_sha256`; downgrade снимает всё и не переносит пропущенные события."""
    command.upgrade(alembic_config, "head")
    command.downgrade(alembic_config, SEAM_REVISION)
    with psycopg.connect(live_settings.libpq_dsn, autocommit=True) as conn:
        conn.execute("TRUNCATE documents, clients, erp_incoming_events RESTART IDENTITY CASCADE")
        for name in ("A", "B"):
            conn.execute("INSERT INTO clients (name) VALUES (%s)", (name,))
        insert_doc = (
            "INSERT INTO documents (client_id, type, title, filename, mime, size_bytes, "
            "erp_document_id) VALUES (%s, 'other', 'Док', 'd.pdf', 'application/pdf', 0, %s)"
        )
        conn.execute(insert_doc, (1, 77))
        conn.execute(insert_doc, (2, 77))  # тот же документ у другого клиента — отдельная строка
        conn.execute(insert_doc, (1, None))
        conn.execute(insert_doc, (1, None))  # NULL не конфликтует
        with pytest.raises(psycopg.errors.UniqueViolation):
            conn.execute(insert_doc, (1, 77))
        conn.execute(
            "INSERT INTO erp_incoming_events (event_id, event_type, status, error, payload, "
            "body_sha256) VALUES ('s-1', 'warehouse.exploded', 'skipped', 'unknown', '{}', 'ab')"
        )
        conn.execute(
            "INSERT INTO erp_incoming_events (event_id, event_type, status, payload) "
            "VALUES ('r-1', 'quote.sent', 'received', '{}')"
        )

    command.downgrade(alembic_config, "0028_erp_webhook_reliability")
    with psycopg.connect(live_settings.libpq_dsn, autocommit=True) as conn:
        columns = {
            r[0]
            for r in conn.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name IN ('documents', 'erp_incoming_events')"
            ).fetchall()
        }
        assert not columns & {"erp_document_id", "body_sha256"}
        assert conn.execute("SELECT event_id FROM erp_incoming_events").fetchall() == [("r-1",)]
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute(
                "INSERT INTO erp_incoming_events (event_id, event_type, status, payload) "
                "VALUES ('s-2', 'x', 'skipped', '{}')"
            )

    command.upgrade(alembic_config, "head")
    with psycopg.connect(live_settings.libpq_dsn, autocommit=True) as conn:
        index = conn.execute(
            "SELECT indexdef FROM pg_indexes WHERE indexname = 'uq_documents_client_erp_document'"
        ).fetchone()
        assert index is not None
        assert "UNIQUE" in index[0]
        assert "erp_document_id IS NOT NULL" in index[0]


def test_rt_bus_revision_replaces_the_webhook_journal_and_is_reversible(
    alembic_config: Config, live_settings: Settings
) -> None:
    """B4: четыре таблицы rt_bus и `erp_event_notices` приходят, `erp_incoming_events` уходит;
    downgrade возвращает пустой журнал вебхуков в прежней форме."""
    bus_tables = (
        "rt_bus_outbox",
        "rt_bus_delivery",
        "rt_bus_inbox",
        "rt_bus_subscriber_state",
        "erp_event_notices",
    )
    sql = "SELECT tablename FROM pg_tables WHERE tablename = ANY(%s) ORDER BY tablename"

    command.upgrade(alembic_config, "head")
    with psycopg.connect(live_settings.libpq_dsn, autocommit=True) as conn:
        assert [r[0] for r in conn.execute(sql, (list(bus_tables),)).fetchall()] == sorted(
            bus_tables
        )
        assert conn.execute(sql, (["erp_incoming_events"],)).fetchall() == []

    command.downgrade(alembic_config, "0038_platform_role_version")
    with psycopg.connect(live_settings.libpq_dsn, autocommit=True) as conn:
        assert conn.execute(sql, (list(bus_tables),)).fetchall() == []
        assert conn.execute(sql, (["erp_incoming_events"],)).fetchall() == [
            ("erp_incoming_events",)
        ]
        conn.execute(
            "INSERT INTO erp_incoming_events (event_id, event_type, status, payload) "
            "VALUES ('s-1', 'warehouse.exploded', 'skipped', '{}')"
        )

    command.upgrade(alembic_config, "head")
    with psycopg.connect(live_settings.libpq_dsn, autocommit=True) as conn:
        assert len(conn.execute(sql, (list(bus_tables),)).fetchall()) == len(bus_tables)


def test_user_erp_role_codes_column_comes_and_goes_with_the_revision(
    alembic_config: Config, live_settings: Settings
) -> None:
    """FIX-63: `users.erp_role_codes` — пустой массив по умолчанию, только коды каталога;
    downgrade колонку снимает."""
    command.upgrade(alembic_config, "head")
    with psycopg.connect(live_settings.libpq_dsn, autocommit=True) as conn:
        conn.execute("TRUNCATE users RESTART IDENTITY CASCADE")
        conn.execute(
            "INSERT INTO users (email, password_hash, full_name) VALUES ('a@x.uz', 'x', 'A')"
        )
        assert conn.execute("SELECT erp_role_codes FROM users").fetchone() == ([],)
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute("UPDATE users SET erp_role_codes = '[\"ROOT\"]'::jsonb")

    command.downgrade(alembic_config, "0030_lead_consent_erp_request")
    with psycopg.connect(live_settings.libpq_dsn, autocommit=True) as conn:
        assert conn.execute(
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_name = 'users' AND column_name = 'erp_role_codes'"
        ).fetchone() == (0,)

    command.upgrade(alembic_config, "head")


def test_user_platform_roles_and_position_come_and_go_with_the_revision(
    alembic_config: Config, live_settings: Settings
) -> None:
    """CRM-01: `users.platform_roles` — пустой массив по умолчанию, только коды контракта;
    `position` — до 120 символов; downgrade обе колонки снимает. Столбец с кодами в R-1 удалён
    миграцией 0036 (роли — данные): проверяем его на ревизии 0035, где downgrade его вернул."""
    command.upgrade(alembic_config, "head")
    command.downgrade(alembic_config, "0035_platform_roles_data")
    with psycopg.connect(live_settings.libpq_dsn, autocommit=True) as conn:
        conn.execute("TRUNCATE users RESTART IDENTITY CASCADE")
        conn.execute(
            "INSERT INTO users (email, password_hash, full_name) VALUES ('a@x.uz', 'x', 'A')"
        )
        assert conn.execute("SELECT platform_roles, position FROM users").fetchone() == ([], None)
        conn.execute('UPDATE users SET platform_roles = \'["MANAGER", "ADMIN"]\'::jsonb')
        for bad in ('["ROOT"]', '["manager"]', '"MANAGER"', "{}"):
            with pytest.raises(psycopg.errors.CheckViolation):
                conn.execute("UPDATE users SET platform_roles = %s::jsonb", (bad,))
        conn.execute("UPDATE users SET position = %s", ("я" * 120,))
        with pytest.raises(psycopg.errors.StringDataRightTruncation):
            conn.execute("UPDATE users SET position = %s", ("я" * 121,))

    command.downgrade(alembic_config, "0031_user_erp_role_codes")
    with psycopg.connect(live_settings.libpq_dsn, autocommit=True) as conn:
        assert conn.execute(
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_name = 'users' AND column_name IN ('platform_roles', 'position')"
        ).fetchone() == (0,)

    command.upgrade(alembic_config, "head")


def _seed_user(conn: psycopg.Connection, email: str, role: str | None, **columns: object) -> int:
    """Пользователь с базовой ролью CRM (`user_roles`) и произвольными колонками `users`."""
    names = ["email", "password_hash", "full_name", *columns]
    marks = ", ".join(["%s"] * len(names))
    sql = f"INSERT INTO users ({', '.join(names)}) VALUES ({marks}) RETURNING id"  # noqa: S608
    row = conn.execute(sql, [email, "x", email, *columns.values()]).fetchone()
    assert row is not None
    if role is not None:
        conn.execute(
            "INSERT INTO user_roles (user_id, role_id) SELECT %s, id FROM roles WHERE name = %s",
            (row[0], role),
        )
    return int(row[0])


def test_admin_backfill_sets_platform_admin_only_for_active_admins_without_roles(
    alembic_config: Config, live_settings: Settings
) -> None:
    """CRM-01b: активному admin с пустыми `platform_roles` — `["ADMIN"]`, доступ `crm+erp` и задача
    провижининга, если ERP не было; уже заданные роли, неактивные и не-admin не трогаются; повтор —
    без изменений; downgrade — no-op."""
    command.upgrade(alembic_config, "head")
    command.downgrade(alembic_config, "0032_user_platform_roles")
    with psycopg.connect(live_settings.libpq_dsn, autocommit=True) as conn:
        conn.execute("TRUNCATE users, audit_log, procrastinate_jobs RESTART IDENTITY CASCADE")
        setup_admin = _seed_user(conn, "setup@x.uz", "admin")
        admin_with_erp = _seed_user(
            conn, "erp@x.uz", "admin", platform_access='["crm", "erp"]', erp_role_codes='["HEAD"]'
        )
        has_roles = _seed_user(conn, "roles@x.uz", "admin", platform_roles='["MANAGER"]')
        inactive = _seed_user(conn, "off@x.uz", "admin", is_active=False)
        manager = _seed_user(conn, "mgr@x.uz", "manager")
        no_role = _seed_user(conn, "none@x.uz", None)

    command.upgrade(alembic_config, "0033_admin_platform_roles")

    snapshot_sql = (
        "SELECT id, platform_roles, platform_access, erp_role_codes FROM users ORDER BY id"
    )
    with psycopg.connect(live_settings.libpq_dsn, autocommit=True) as conn:
        rows = {r[0]: r[1:] for r in conn.execute(snapshot_sql).fetchall()}
        assert rows[setup_admin] == (["ADMIN"], ["crm", "erp"], [])
        assert rows[admin_with_erp] == (["ADMIN"], ["crm", "erp"], ["HEAD"])
        assert rows[has_roles] == (["MANAGER"], ["crm"], [])
        assert rows[inactive] == ([], ["crm"], [])
        assert rows[manager] == ([], ["crm"], [])
        assert rows[no_role] == ([], ["crm"], [])
        # Провижининг ERP — только тем, у кого доступа не было (у второго он уже выдан).
        jobs = conn.execute(
            "SELECT task_name, lock, args FROM procrastinate_jobs ORDER BY id"
        ).fetchall()
        assert jobs == [("erp_provision_user", f"erp_user:{setup_admin}", {"user_id": setup_admin})]
        audited = conn.execute(
            "SELECT entity_id, actor_type FROM audit_log WHERE action = 'user.update' ORDER BY id"
        ).fetchall()
        assert audited == [(str(setup_admin), "system"), (str(admin_with_erp), "system")]

    # Повтор (re-upgrade после no-op downgrade) ничего не меняет и не ставит задач.
    command.downgrade(alembic_config, "0032_user_platform_roles")
    with psycopg.connect(live_settings.libpq_dsn, autocommit=True) as conn:
        assert {r[0]: r[1:] for r in conn.execute(snapshot_sql).fetchall()} == rows
    command.upgrade(alembic_config, "0033_admin_platform_roles")
    with psycopg.connect(live_settings.libpq_dsn, autocommit=True) as conn:
        assert {r[0]: r[1:] for r in conn.execute(snapshot_sql).fetchall()} == rows
        assert conn.execute("SELECT count(*) FROM procrastinate_jobs").fetchone() == (1,)
        assert conn.execute("SELECT count(*) FROM audit_log").fetchone() == (2,)

    command.upgrade(alembic_config, "head")


def test_user_language_defaults_to_ru_accepts_only_known_codes_and_leaves_with_downgrade(
    alembic_config: Config, live_settings: Settings
) -> None:
    """CRM-01b (Q-PLT-10-1 п. 6): `users.language` — ru|uz|en, по умолчанию ru; downgrade снимает"""
    command.upgrade(alembic_config, "head")
    with psycopg.connect(live_settings.libpq_dsn, autocommit=True) as conn:
        conn.execute("TRUNCATE users RESTART IDENTITY CASCADE")
        _seed_user(conn, "a@x.uz", None)
        assert conn.execute("SELECT language FROM users").fetchone() == ("ru",)
        for good in ("uz", "en", "ru"):
            conn.execute("UPDATE users SET language = %s", (good,))
        for bad in ("de", "RU", ""):
            with pytest.raises(psycopg.errors.CheckViolation):
                conn.execute("UPDATE users SET language = %s", (bad,))

    command.downgrade(alembic_config, "0033_admin_platform_roles")
    with psycopg.connect(live_settings.libpq_dsn, autocommit=True) as conn:
        assert conn.execute(
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_name = 'users' AND column_name = 'language'"
        ).fetchone() == (0,)

    command.upgrade(alembic_config, "head")


PROFILE_SQL = """
SELECT
  (SELECT count(*) FROM information_schema.columns WHERE table_name = 'users'
     AND column_name IN ('phone', 'timezone', 'email_signature', 'tg_username', 'avatar_key',
                         'avatar_updated_at', 'tg_linked_at', 'deputy_user_id', 'deputy_from',
                         'deputy_to', 'password_changed_at')),
  (SELECT count(*) FROM information_schema.tables
     WHERE table_name IN ('staff_telegram_links', 'password_reset_tokens'))
"""


def test_staff_profile_revision_is_reversible_and_has_one_head(
    alembic_config: Config, live_settings: Settings
) -> None:
    """W15-H6: одиннадцать колонок профиля и две таблицы приходят и уходят; голова ревизий одна."""
    from alembic.script import ScriptDirectory

    assert len(ScriptDirectory.from_config(alembic_config).get_heads()) == 1
    command.upgrade(alembic_config, "head")
    with psycopg.connect(live_settings.libpq_dsn) as conn:
        assert conn.execute(PROFILE_SQL).fetchone() == (11, 2)

    command.downgrade(alembic_config, "0041_external_cause_alerts")
    with psycopg.connect(live_settings.libpq_dsn) as conn:
        assert conn.execute(PROFILE_SQL).fetchone() == (0, 0)

    command.upgrade(alembic_config, "head")
    with psycopg.connect(live_settings.libpq_dsn) as conn:
        assert conn.execute(PROFILE_SQL).fetchone() == (11, 2)


INBOUND_BEFORE = "add9f58d0dab"


def _statuses(settings: Settings) -> list[tuple[str, str, str | None]]:
    sql = "SELECT message_id, status, outcome FROM inbound_mail ORDER BY id"
    with psycopg.connect(settings.libpq_dsn) as conn:
        return [(str(a), str(b), c) for a, b, c in conn.execute(sql).fetchall()]


def test_inbound_mail_statuses_become_done_with_outcome_and_back(
    alembic_config: Config, live_settings: Settings
) -> None:
    """W18A-P2-3: `registered | lead | archived` → `done` + итог; откат — прежний статус."""
    command.upgrade(alembic_config, "head")
    command.downgrade(alembic_config, INBOUND_BEFORE)
    old = ["new", "spam", "registered", "lead", "archived"]
    with psycopg.connect(live_settings.libpq_dsn) as conn:
        conn.execute("TRUNCATE inbound_mail RESTART IDENTITY CASCADE")
        for n, status in enumerate(old):
            conn.execute(
                "INSERT INTO inbound_mail "
                "(message_id, mailbox, uidvalidity, uid, status, to_addrs) "
                "VALUES (%s, 'INBOX', 1, %s, %s, '[\"a@example.test\", \"b@example.test\"]')",
                (f"m{n}", n, status),
            )
        conn.commit()

    command.upgrade(alembic_config, "head")
    assert _statuses(live_settings) == [
        ("m0", "new", None),
        ("m1", "spam", None),
        ("m2", "done", "registered"),
        ("m3", "done", "lead"),
        ("m4", "done", "archived"),
    ]
    with psycopg.connect(live_settings.libpq_dsn) as conn:
        row = conn.execute(
            "SELECT to_addrs, cc_addrs, personal, thread_root_id, activity_at IS NOT NULL "
            "FROM inbound_mail WHERE message_id = 'm0'"
        ).fetchone()
    assert row is not None
    assert row[0] == ["a@example.test", "b@example.test"], "старые строки: всё в «Кому»"
    assert (row[1], row[2], row[3], row[4]) == ([], False, None, True)

    command.downgrade(alembic_config, INBOUND_BEFORE)
    with psycopg.connect(live_settings.libpq_dsn) as conn:
        back = [r[0] for r in conn.execute("SELECT status FROM inbound_mail ORDER BY id")]
    assert back == old
    command.upgrade(alembic_config, "head")


MAIL_HTML_BEFORE = "563bd9b32ffd"


def test_inbound_mail_html_columns_keep_old_rows_and_roll_back(
    alembic_config: Config, live_settings: Settings
) -> None:
    """W18A-P2-4: колонки HTML и цитаты приходят с пустыми значениями у старых писем и уходят."""
    command.upgrade(alembic_config, MAIL_HTML_BEFORE)
    with psycopg.connect(live_settings.libpq_dsn) as conn:
        conn.execute("TRUNCATE inbound_mail RESTART IDENTITY CASCADE")
        conn.execute(
            "INSERT INTO inbound_mail (message_id, mailbox, uidvalidity, uid, text) "
            "VALUES ('old', 'INBOX', 1, 1, 'Старое письмо')"
        )
        conn.commit()

    command.upgrade(alembic_config, "head")
    sql = "SELECT text, text_tail, html_sanitized, html_remote_images FROM inbound_mail"
    with psycopg.connect(live_settings.libpq_dsn) as conn:
        assert conn.execute(sql).fetchone() == ("Старое письмо", "", None, 0)

    command.downgrade(alembic_config, MAIL_HTML_BEFORE)
    cols = (
        "SELECT count(*) FROM information_schema.columns WHERE table_name = 'inbound_mail' "
        "AND column_name IN ('text_tail', 'html_sanitized', 'html_remote_images')"
    )
    with psycopg.connect(live_settings.libpq_dsn) as conn:
        assert conn.execute(cols).fetchone() == (0,)
        assert conn.execute("SELECT text FROM inbound_mail").fetchone() == ("Старое письмо",)
    command.upgrade(alembic_config, "head")


def test_inbound_mail_downgrade_keeps_the_copy_in_to_addrs(
    alembic_config: Config, live_settings: Settings
) -> None:
    """W18A-P2-3: после отката адреса копии не теряются — до этой ревизии всё было в «Кому»."""
    command.upgrade(alembic_config, "head")
    with psycopg.connect(live_settings.libpq_dsn) as conn:
        conn.execute("TRUNCATE inbound_mail RESTART IDENTITY CASCADE")
        conn.execute(
            "INSERT INTO inbound_mail (message_id, mailbox, uidvalidity, uid, to_addrs, cc_addrs) "
            "VALUES ('c1', 'INBOX', 1, 1, '[\"to@example.test\"]', "
            '\'["cc1@example.test", "cc2@example.test"]\'), '
            "('c2', 'INBOX', 1, 2, '[\"only@example.test\"]', '[]')"
        )
        conn.commit()

    command.downgrade(alembic_config, INBOUND_BEFORE)

    with psycopg.connect(live_settings.libpq_dsn) as conn:
        rows: dict[str, list[str]] = {
            str(k): list(v)
            for k, v in conn.execute("SELECT message_id, to_addrs FROM inbound_mail").fetchall()
        }
    assert rows["c1"] == ["to@example.test", "cc1@example.test", "cc2@example.test"]
    assert rows["c2"] == ["only@example.test"]
    command.upgrade(alembic_config, "head")


def test_mail_types_revision_seeds_types_moves_old_hints_and_rolls_back(
    alembic_config: Config, live_settings: Settings
) -> None:
    """MAIL-TYPES: восемь типов, подсказки помощника до типов переезжают в тип, откат без потерь."""
    command.upgrade(alembic_config, "head")
    command.downgrade(alembic_config, "76abc53006ad")
    rows = [("a", "buyer"), ("b", "official"), ("c", "supplier_doc"), ("d", "other")]
    with psycopg.connect(live_settings.libpq_dsn) as conn:
        conn.execute("TRUNCATE inbound_mail RESTART IDENTITY CASCADE")
        for mid, kind in rows:
            conn.execute(
                "INSERT INTO inbound_mail (message_id, mailbox, uidvalidity, uid, "
                "assist_status, assist_kind, assist_action) "
                "VALUES (%s, 'INBOX', 1, 1, 'done', %s, 'lead')",
                (mid, kind),
            )
        conn.commit()

    command.upgrade(alembic_config, "head")
    with psycopg.connect(live_settings.libpq_dsn) as conn:
        types = conn.execute("SELECT code FROM mail_types ORDER BY position").fetchall()
        assert [t[0] for t in types] == [
            "client_request",
            "cooperation",
            "meeting",
            "supplier_price",
            "supplier_invoice",
            "official",
            "mailing",
            "spam",
        ]
        moved = conn.execute(
            "SELECT message_id, type_code, type_source FROM inbound_mail ORDER BY message_id"
        ).fetchall()
        assert moved == [
            ("a", "client_request", "ai"),
            ("b", "official", "ai"),
            ("c", "supplier_invoice", "ai"),
            ("d", None, None),
        ]
        conn.execute(
            "UPDATE inbound_mail SET status = 'done', outcome = 'price', "
            "assist_action = 'create_lead' WHERE message_id = 'a'"
        )
        conn.execute(
            "UPDATE inbound_mail SET assist_action = 'register_incoming' WHERE message_id = 'b'"
        )
        conn.commit()

    command.downgrade(alembic_config, "76abc53006ad")
    with psycopg.connect(live_settings.libpq_dsn) as conn:
        tables = (
            "SELECT count(*) FROM pg_tables WHERE tablename IN ('mail_types', 'mail_sender_rules')"
        )
        assert conn.execute(tables).fetchone() == (0,)
        back = conn.execute(
            "SELECT message_id, outcome, archive_reason, assist_action FROM inbound_mail "
            "WHERE message_id IN ('a', 'b') ORDER BY message_id"
        ).fetchall()
        assert back == [
            ("a", "archived", "Прайс загружен", "lead"),
            ("b", None, None, "register"),
        ]
    command.upgrade(alembic_config, "head")
