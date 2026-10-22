"""L9: миграция Django совпадает с моделями и с таблицами SQLAlchemy (столбцы, типы, NULL, индексы, ограничения)."""

from __future__ import annotations

import io
from typing import Any

import pytest
from django.core.management import call_command
from django.db import connection

from .conftest import DRIVER, _admin_execute

pytestmark = pytest.mark.pg

TABLES = ("rt_bus_outbox", "rt_bus_delivery", "rt_bus_inbox", "rt_bus_subscriber_state")

COLUMNS = """
SELECT table_name, column_name, data_type, character_maximum_length, is_nullable, is_identity
FROM information_schema.columns WHERE table_name = ANY(%(t)s) ORDER BY table_name, column_name
"""
INDEXES = "SELECT tablename, indexname, indexdef FROM pg_indexes WHERE tablename = ANY(%(t)s) ORDER BY 1, 2"
CONSTRAINTS = """
SELECT conrelid::regclass::text AS tbl, conname, contype FROM pg_constraint
WHERE conrelid::regclass::text = ANY(%(t)s) ORDER BY 1, 2
"""


def snapshot(cursor: Any) -> dict[str, list[tuple[Any, ...]]]:
    out = {}
    for name, query in (("columns", COLUMNS), ("indexes", INDEXES), ("constraints", CONSTRAINTS)):
        cursor.execute(query, {"t": list(TABLES)})
        out[name] = [tuple(r) for r in cursor.fetchall()]
    return out


def test_no_missing_migrations() -> None:
    out = io.StringIO()
    call_command("makemigrations", "rt_bus", "--check", "--dry-run", stdout=out)
    assert "No changes detected" in out.getvalue()


def test_same_schema_as_sqlalchemy() -> None:
    from sqlalchemy import MetaData, create_engine

    from rt_bus.sqlalchemy import bus_tables

    from ..conftest import pg_url

    name = f"rt_bus_schema_sa_{DRIVER}"
    _admin_execute([f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)', f'CREATE DATABASE "{name}"'])
    head = pg_url().rpartition("/")[0]
    engine = create_engine(f"{head}/{name}".replace("postgresql://", f"postgresql+{DRIVER}://", 1))
    metadata = MetaData()
    bus_tables(metadata)
    metadata.create_all(engine)
    raw = engine.raw_connection()
    try:
        cursor = raw.cursor()
        sa_schema = snapshot(cursor)
    finally:
        raw.close()
        engine.dispose()
    with connection.cursor() as cursor:
        dj_schema = snapshot(cursor)
    assert len(sa_schema["columns"]) == 44
    assert sa_schema == dj_schema
