"""kb-mcp по HTTP: инструменты доступны только с валидным подписанным контекстом."""

from collections.abc import AsyncIterator

import httpx2
import pytest
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
from tests.integration.servers import free_port, running


@pytest.fixture
async def kb_url(
    sessions: async_sessionmaker[AsyncSession], live_settings: Settings
) -> AsyncIterator[str]:
    container = Container(live_settings)
    container.__dict__["session_factory"] = sessions
    container.__dict__["embedder"] = FakeEmbedder()
    port = free_port()
    async with running(build_app(create_server(container), "kb-mcp", port), port) as url:
        yield url


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
