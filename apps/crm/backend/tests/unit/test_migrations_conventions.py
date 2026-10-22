"""Соглашения о миграциях (CONVENTIONS.md §4): имя файла и реализованный downgrade."""

import ast
import re
from pathlib import Path

import procrastinate
import pytest

ALEMBIC_DIR = Path(__file__).parents[2] / "alembic"
MIGRATIONS = sorted((ALEMBIC_DIR / "versions").glob("*.py"))
FILENAME_RE = re.compile(r"^\d{8}_\d{4}_[a-z0-9_]+\.py$")


def test_there_is_at_least_one_migration() -> None:
    assert MIGRATIONS


@pytest.mark.parametrize("path", MIGRATIONS, ids=lambda p: p.name)
def test_filename_follows_convention(path: Path) -> None:
    assert FILENAME_RE.match(path.name), path.name


@pytest.mark.parametrize("path", MIGRATIONS, ids=lambda p: p.name)
def test_downgrade_is_implemented(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    body = functions["downgrade"].body
    assert not all(isinstance(stmt, ast.Pass) for stmt in body), "downgrade() пустой"


def test_procrastinate_schema_snapshot_matches_installed_version() -> None:
    """Обновление Procrastinate требует ревизии Alembic с его SQL-миграциями (ADR-0006)."""
    snapshots = sorted((ALEMBIC_DIR / "sql").glob("procrastinate_*_schema.sql"))
    assert [p.name for p in snapshots] == ["procrastinate_3.10.0_schema.sql"]
    assert procrastinate.__version__ == "3.10.0", (
        "Версия Procrastinate изменилась: добавьте миграцию Alembic, применяющую "
        "SQL из procrastinate/sql/migrations, и обновите этот тест."
    )
