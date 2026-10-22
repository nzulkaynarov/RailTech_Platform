"""Django-адаптер на настоящем PostgreSQL. Драйвер — RT_BUS_DJANGO_DRIVER: psycopg2 (как ERP) или psycopg (3).

Отдельный процесс pytest: Django выбирает драйвер при импорте бэкенда (psycopg 3, если он импортируется).
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from ..conftest import pg_url

DRIVER = os.environ.get("RT_BUS_DJANGO_DRIVER", "psycopg2")
if DRIVER == "psycopg2":
    sys.modules["psycopg"] = None  # type: ignore[assignment]  # Django возьмёт psycopg2, как в ERP
os.environ["DJANGO_SETTINGS_MODULE"] = "tests.django_settings"
os.environ["RT_BUS_TEST_DJANGO_DB"] = f"rt_bus_dj_{DRIVER}"


def _admin_execute(statements: list[str]) -> None:
    url = pg_url()
    if DRIVER == "psycopg2":
        import psycopg2

        conn = psycopg2.connect(url)
        conn.autocommit = True
        with conn.cursor() as cur:
            for statement in statements:
                cur.execute(statement)
        conn.close()
    else:
        import psycopg

        with psycopg.connect(url, autocommit=True) as conn3:
            for statement in statements:
                conn3.execute(statement.encode())


@pytest.fixture(scope="session", autouse=True)
def django_db() -> Iterator[None]:
    name = os.environ["RT_BUS_TEST_DJANGO_DB"]
    _admin_execute([f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)', f'CREATE DATABASE "{name}"'])
    import django
    from django.core.management import call_command

    django.setup()
    call_command("migrate", "rt_bus", verbosity=0)
    yield
    from django.db import connections

    connections.close_all()


@pytest.fixture(autouse=True)
def clean_tables(django_db: None) -> None:
    from django.db import connection

    with connection.cursor() as cursor:
        cursor.execute(
            "TRUNCATE rt_bus_outbox, rt_bus_delivery, rt_bus_inbox, rt_bus_subscriber_state RESTART IDENTITY"
        )


class SyncHub:
    """MockTransport (sync): запросы подписчикам по имени хоста, ответы — по умолчанию 200."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.responders: dict[str, Callable[[httpx.Request], httpx.Response]] = {}
        self.clients: list[httpx.Client] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        responder = self.responders.get(request.url.host.split(".")[0])
        return responder(request) if responder else httpx.Response(200, json={"status": "accepted"})

    def to(self, subscriber: str) -> list[httpx.Request]:
        return [r for r in self.requests if r.url.host.split(".")[0] == subscriber]

    def client(self) -> httpx.Client:
        client = httpx.Client(transport=httpx.MockTransport(self))
        self.clients.append(client)
        return client


@pytest.fixture
def hub() -> Iterator[SyncHub]:
    h = SyncHub()
    yield h
    for client in h.clients:
        client.close()


@pytest.fixture
def make_bus(clock: Any, subscriptions_file: Path, hub: SyncHub) -> Callable[..., Any]:
    from rt_bus import HandlerRegistry
    from rt_bus.django.bus import DjangoBus

    from ..conftest import make_config

    def factory(service: str = "erp", *, registry: Any = None, http: Any = None, **config: Any) -> DjangoBus:
        return DjangoBus(
            make_config(service, clock, subscriptions_file, **config),
            registry=registry or HandlerRegistry(),
            http=http or hub.client(),
        )

    return factory


def rows(query: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    from django.db import connection

    with connection.cursor() as cursor:
        cursor.execute(query, params or {})
        if cursor.description is None:
            return []
        names = [c[0] for c in cursor.description]
        return [dict(zip(names, r, strict=True)) for r in cursor.fetchall()]
