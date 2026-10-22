"""Фикстуры адаптера SQLAlchemy: настоящий PostgreSQL, два драйвера (psycopg 3 — как CRM, asyncpg)."""

from __future__ import annotations

import inspect
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import MetaData, create_engine, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from rt_bus import HandlerRegistry
from rt_bus.sqlalchemy import AsyncBus, bus_tables

from ..conftest import Clock, make_config, recreate_database

Responder = Callable[[httpx.Request], httpx.Response | Awaitable[httpx.Response]]


@pytest.fixture(scope="session")
def sa_database() -> str:
    url = recreate_database("rt_bus_sa")
    engine = create_engine(url.replace("postgresql://", "postgresql+psycopg://", 1))
    metadata = MetaData()
    bus_tables(metadata)
    metadata.create_all(engine)
    engine.dispose()
    return url


@pytest.fixture(params=["psycopg", "asyncpg"])
async def engine(request: pytest.FixtureRequest, sa_database: str) -> AsyncIterator[AsyncEngine]:
    eng = create_async_engine(sa_database.replace("postgresql://", f"postgresql+{request.param}://", 1), pool_size=6)
    async with eng.begin() as conn:
        await conn.execute(
            text("TRUNCATE rt_bus_outbox, rt_bus_delivery, rt_bus_inbox, rt_bus_subscriber_state RESTART IDENTITY")
        )
    yield eng
    await eng.dispose()


@pytest.fixture
def sessions(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


class Hub:
    """MockTransport: запросы подписчикам по имени хоста (`crm.test` → `crm`), ответы — по умолчанию 200."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.responders: dict[str, Responder] = {}
        self.clients: list[httpx.AsyncClient] = []

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        responder = self.responders.get(request.url.host.split(".")[0])
        if responder is None:
            return httpx.Response(200, json={"status": "accepted"})
        result = responder(request)
        return await result if inspect.isawaitable(result) else result

    def to(self, subscriber: str) -> list[httpx.Request]:
        return [r for r in self.requests if r.url.host.split(".")[0] == subscriber]

    def client(self) -> httpx.AsyncClient:
        client = httpx.AsyncClient(transport=httpx.MockTransport(self))
        self.clients.append(client)
        return client


@pytest.fixture
async def hub() -> AsyncIterator[Hub]:
    h = Hub()
    yield h
    for client in h.clients:
        await client.aclose()


@pytest.fixture
def make_bus(
    sessions: async_sessionmaker[AsyncSession], clock: Clock, subscriptions_file: Path, hub: Hub
) -> Callable[..., AsyncBus]:
    def factory(
        service: str = "erp",
        *,
        registry: HandlerRegistry | None = None,
        http: httpx.AsyncClient | None = None,
        **config: Any,
    ) -> AsyncBus:
        return AsyncBus(
            make_config(service, clock, subscriptions_file, **config),
            sessions,
            registry=registry or HandlerRegistry(),
            http=http or hub.client(),
        )

    return factory


async def rows(sessions: async_sessionmaker[AsyncSession], query: str, **params: Any) -> list[dict[str, Any]]:
    async with sessions() as session:
        return [dict(r) for r in (await session.execute(text(query), params)).mappings().all()]
