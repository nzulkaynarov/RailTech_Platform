"""Integration-тесты: реальные Postgres (+pgvector) и MinIO.

В CI это service containers (`.github/workflows/ci.yml`); параметры подключения
передаются через те же переменные окружения, что и в приложении.
"""

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

from app.config import Settings

ALEMBIC_INI = Path(__file__).parents[2] / "alembic.ini"


@pytest.fixture(scope="session")
def live_settings() -> Settings:
    return Settings(_env_file=None, app_env="test")


@pytest.fixture
def alembic_config() -> Config:
    return Config(str(ALEMBIC_INI))


@pytest.fixture
def migrated_db(alembic_config: Config) -> None:
    command.upgrade(alembic_config, "head")
