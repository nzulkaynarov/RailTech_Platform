"""One Alembic head, checked without a database.

The integration suite checks the same, but it does not run on push to main or in the merge
queue; two PRs that branch from the same parent must be caught before they land together.
"""

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

BACKEND = Path(__file__).resolve().parents[1]


def test_migrations_have_a_single_head() -> None:
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "alembic"))
    heads = ScriptDirectory.from_config(config).get_heads()
    assert len(heads) == 1, f"several Alembic heads: {heads}; re-chain the newer migration"
