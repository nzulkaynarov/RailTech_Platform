"""Общие фикстуры. Тесты из tests/unit не должны требовать внешних сервисов."""

from pathlib import Path

import pytest

from app.config import Settings

TESTS_DIR = Path(__file__).parent
MARKERS_BY_DIR = {"unit": "unit", "integration": "integration", "e2e": "e2e"}


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        relative = Path(item.path).relative_to(TESTS_DIR)
        marker = MARKERS_BY_DIR.get(relative.parts[0])
        if marker is not None:
            item.add_marker(marker)


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,
        app_env="test",
        postgres_host="db.invalid",
        postgres_password="test-password",
        s3_endpoint="http://s3.invalid:9000",
        litellm_base_url="http://litellm.invalid:4000",
        ready_check_timeout_s=0.5,
    )
