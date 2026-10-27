"""Общие фикстуры. Тесты из tests/unit не должны требовать внешних сервисов."""

import os
from pathlib import Path

import pytest

from app.config import Settings

TESTS_DIR = Path(__file__).parent


def _name_database_for_xdist_worker() -> None:
    """У воркера xdist своя база `<БД>_gwN` (создаёт её integration-фикстура `_worker_database`).

    Имя нужно подставить сразу при старте воркера: `get_settings()` кэшируется, а очередь
    Procrastinate (`app.tasks.queue`) берёт DSN при импорте модуля. Без xdist — ничего не делает.
    """
    worker = os.environ.get("PYTEST_XDIST_WORKER")
    if worker is not None:
        os.environ["POSTGRES_DB"] = f"{Settings(_env_file=None).postgres_db}_{worker}"


_name_database_for_xdist_worker()
MARKERS_BY_DIR = {"unit": "unit", "integration": "integration", "e2e": "e2e"}


def _integration_workers(config: pytest.Config) -> int:
    """Сколько воркеров xdist нужно прогону; 0 — идти одним процессом.

    Параллельность включается сама для целого прогона `-m integration` (так CI вызывает
    `pytest -m integration`, строка в ci.yml не нужна): по воркеру на ядро, но не больше 4. Не
    включается, если xdist не установлен, `-n` указан явно, выбраны отдельные файлы/тесты или `-k`
    (там запуск воркеров и баз дороже самих тестов). `ITEST_WORKERS=<N>` задаёт число явно,
    0 или 1 — выключает.
    """
    option = config.option
    markexpr = (option.markexpr or "").strip()
    if not hasattr(option, "numprocesses") or option.numprocesses is not None:
        return 0
    if os.environ.get("PYTEST_XDIST_WORKER") or markexpr != "integration":
        return 0
    explicit = os.environ.get("ITEST_WORKERS")
    if explicit is not None:
        return int(explicit) if int(explicit) > 1 else 0
    selected = option.keyword or any("::" in arg or Path(arg).is_file() for arg in config.args)
    cpus = os.cpu_count() or 1
    return 0 if selected or cpus < 2 else min(cpus, 4)


@pytest.hookimpl(tryfirst=True)
def pytest_cmdline_main(config: pytest.Config) -> None:
    workers = _integration_workers(config)
    if workers:
        config.option.numprocesses = workers
        config.option.dist = "loadfile"  # модуль целиком на одном воркере: общие фикстуры модуля


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
