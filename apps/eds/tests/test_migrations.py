"""Миграции Alembic: одна голова, нет дрейфа от моделей, подъём и откат без остатка (pg)."""

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text

from app.config import Settings
from app.models import Base
from tests.conftest import alembic_config


def test_single_head() -> None:
    heads = ScriptDirectory.from_config(alembic_config()).get_heads()
    assert len(heads) == 1, f"в alembic/versions несколько голов: {heads}"


@pytest.mark.pg
def test_models_match_migrations(database: str, settings: Settings) -> None:
    engine = create_engine(settings.sqlalchemy_url)
    try:
        with engine.connect() as conn:
            context = MigrationContext.configure(
                conn,
                opts={
                    "compare_type": True,
                    "include_object": lambda obj, name, type_, *_: (
                        not (type_ == "table" and (name or "").startswith("procrastinate_"))
                    ),
                },
            )
            assert compare_metadata(context, Base.metadata) == []
    finally:
        engine.dispose()


@pytest.mark.pg
def test_downgrade_to_base_and_back(database: str, settings: Settings) -> None:
    cfg = alembic_config()
    engine = create_engine(settings.sqlalchemy_url)
    try:
        command.downgrade(cfg, "base")
        with engine.connect() as conn:
            left = [t for t in inspect(conn).get_table_names() if t != "alembic_version"]
            assert left == []
            assert conn.execute(text("SELECT count(*) FROM pg_type WHERE typname LIKE 'procrastinate%'")).scalar() == 0
    finally:
        command.upgrade(cfg, "head")
        engine.dispose()
