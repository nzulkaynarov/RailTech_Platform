"""Общие фикстуры: контракт (packages/contracts; другой каталог — RT_BUS_TEST_CONTRACTS_DIR), подписки, секреты,
часы, PostgreSQL.

Тесты Django идут отдельным процессом (`RT_BUS_DJANGO_DRIVER=psycopg2|psycopg pytest tests/dj`): драйвер Django
выбирается при импорте, а тесты SQLAlchemy уже загрузили psycopg 3.
"""

from __future__ import annotations

import json
import os
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import yaml

from rt_bus import static_secrets
from rt_bus.core import BusConfig

if os.environ.get("RT_BUS_DJANGO_DRIVER"):
    collect_ignore, collect_ignore_glob = ["sa"], ["test_*.py"]
else:
    collect_ignore, collect_ignore_glob = ["dj"], []

#: Каталог контракта: по умолчанию packages/contracts этого репозитория.
FIXTURES = Path(
    os.environ.get("RT_BUS_TEST_CONTRACTS_DIR") or Path(__file__).resolve().parents[2] / "contracts"
).resolve()
EVENTS_DIR = FIXTURES / "events"
T0 = datetime(2026, 10, 23, 9, 0, tzinfo=UTC)

#: Тестовые секреты пар — заведомо фиктивные строки.
SECRETS = {
    ("erp", "crm"): "test-secret-erp-crm-new,test-secret-erp-crm-old",
    ("erp", "audit"): "test-secret-erp-audit",
    ("erp", "late"): "test-secret-erp-late",
    ("crm", "erp"): "test-secret-crm-erp",
}

SUBSCRIPTIONS: dict[str, Any] = {
    "version": 1,
    "subscribers": [
        {
            "name": "crm",
            "endpoint": "http://crm.test/bus/v1/events",
            "endpoint_env": "RT_BUS_ENDPOINT_CRM",
            "types": ["uz.railtech.erp.*.v1"],
        },
        {
            "name": "erp",
            "endpoint": "http://erp.test/bus/v1/events",
            # erp подписан и на свой тип: издатель себе не доставляет.
            "types": [
                "uz.railtech.crm.client.updated.v1",
                "uz.railtech.crm.contact.*.v1",
                "uz.railtech.erp.deal.won.v1",
            ],
        },
        {"name": "audit", "endpoint": "http://audit.test/bus/v1/events", "types": ["uz.railtech.erp.quote.*.v1"]},
        {
            "name": "off",
            "endpoint": "http://off.test/bus/v1/events",
            "enabled": False,
            "drop": True,  # заглушка: прошлое не нужно, строки доставки не создаются (W11B-G-2)
            "types": ["uz.railtech.erp.*.v1"],
        },
    ],
}


class Clock:
    """Управляемые часы (`BusConfig.clock`)."""

    def __init__(self, start: datetime = T0) -> None:
        self.current = start

    def __call__(self) -> datetime:
        return self.current

    def advance(self, seconds: float) -> datetime:
        self.current += timedelta(seconds=seconds)
        return self.current


def example(rel: str) -> dict[str, Any]:
    """Пример полного конверта B2: `erp/quote.sent.v1` → events/erp/examples/quote.sent.v1.json."""
    domain, name = rel.split("/", 1)
    loaded: dict[str, Any] = json.loads((EVENTS_DIR / domain / "examples" / f"{name}.json").read_text("utf-8"))
    return loaded


def example_data(rel: str) -> dict[str, Any]:
    data: dict[str, Any] = example(rel)["data"]
    return data


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def subscriptions_file(tmp_path: Path) -> Path:
    path = tmp_path / "subscriptions.yaml"
    path.write_text(yaml.safe_dump(SUBSCRIPTIONS, allow_unicode=True), encoding="utf-8")
    return path


@pytest.fixture
def contracts_dir(tmp_path: Path) -> Path:
    """Копия каталога схем (тест может добавить или испортить схему)."""
    target = tmp_path / "contracts" / "events"
    shutil.copytree(EVENTS_DIR, target)
    return target


def make_config(service: str, clock: Clock, subscriptions_file: Path, **overrides: Any) -> BusConfig:
    import random

    params: dict[str, Any] = {
        "service": service,
        "contracts_dir": EVENTS_DIR,
        "subscriptions_path": subscriptions_file,
        "secrets": static_secrets(SECRETS),
        "clock": clock,
        "rng": random.Random(7),
    }
    params.update(overrides)
    return BusConfig(**params)


# --- PostgreSQL ---------------------------------------------------------------------------------------------------


def pg_url() -> str:
    url = os.environ.get("RT_BUS_TEST_DATABASE_URL")
    if not url:
        if os.environ.get("RT_BUS_REQUIRE_PG"):
            pytest.fail("RT_BUS_TEST_DATABASE_URL is required (make test поднимает PostgreSQL сам)")
        pytest.skip("RT_BUS_TEST_DATABASE_URL is not set")
    return url


def recreate_database(name: str) -> str:
    """Пересоздать базу `name` на сервере RT_BUS_TEST_DATABASE_URL; вернуть её URL (postgresql://…)."""
    import psycopg
    from psycopg import sql as psql

    base = pg_url()
    with psycopg.connect(base, autocommit=True) as conn:
        conn.execute(psql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(psql.Identifier(name)))
        conn.execute(psql.SQL("CREATE DATABASE {}").format(psql.Identifier(name)))
    head, _, _ = base.rpartition("/")
    return f"{head}/{name}"


def signed(
    envelope: dict[str, Any], *, publisher: str = "erp", secret: str = "test-secret-erp-crm-new", now: datetime = T0
) -> tuple[dict[str, str], bytes]:
    """Заголовки и тело доставки, как их шлёт издатель."""
    from rt_bus.delivery import build_attempt

    attempt = build_attempt(envelope, publisher=publisher, url="http://x/bus/v1/events", secret=secret, now=now)
    return attempt.headers, attempt.body
