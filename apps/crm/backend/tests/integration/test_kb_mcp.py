"""kb-mcp по HTTP: инструменты доступны только с валидным подписанным контекстом."""

import asyncio
import socket
from collections.abc import AsyncIterator

import httpx2
import pytest
import uvicorn
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.container import Container
from app.mcp.common import build_app
from app.mcp.kb_server import create_server
from app.security.agent_context import HEADER_NAME, issue
from tests.fakes import FakeEmbedder
from tests.integration.kb_seed import seed_kb


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture
async def kb_url(
    sessions: async_sessionmaker[AsyncSession], live_settings: Settings
) -> AsyncIterator[str]:
    container = Container(live_settings)
    container.__dict__["session_factory"] = sessions
    container.__dict__["embedder"] = FakeEmbedder()
    port = free_port()
    app = build_app(create_server(container), "kb-mcp", port)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_config=None))
    task = asyncio.create_task(server.serve())
    while not server.started:  # noqa: ASYNC110 — uvicorn не даёт события старта
        await asyncio.sleep(0.05)
    yield f"http://127.0.0.1:{port}/mcp"
    server.should_exit = True
    await task


async def call(url: str, headers: dict[str, str], tool: str, args: dict[str, object]) -> object:
    async with (
        httpx2.AsyncClient(headers=headers) as http,
        Client(streamable_http_client(url, http_client=http)) as client,
    ):
        return await client.call_tool(tool, args)


async def test_search_with_valid_context(
    kb_url: str, sessions: async_sessionmaker[AsyncSession], live_settings: Settings
) -> None:
    await seed_kb(sessions)
    token = issue(live_settings.agent_context_key_bytes, lead_id=1, mode="prospect", language="ru")
    result = await call(kb_url, {HEADER_NAME: token}, "search_kb", {"query": "касса 1С"})
    assert not result.is_error  # type: ignore[attr-defined]
    payload = result.structured_content  # type: ignore[attr-defined]
    assert payload["hits"][0]["document_title"] == "Кассы RT-POS"


@pytest.mark.parametrize("token", [None, "garbage.sig"], ids=["missing", "forged"])
async def test_rejects_without_valid_context(kb_url: str, token: str | None) -> None:
    headers = {HEADER_NAME: token} if token else {}
    result = await call(kb_url, headers, "list_products", {})
    assert result.is_error  # type: ignore[attr-defined]
