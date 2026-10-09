"""Клиент MCP-инструментов агента (SPEC §7.1, ADR-0008, ADR-0011).

Каждый вызов несёт подписанный `X-Agent-Context`; идентификаторы лида/клиента
в аргументы не передаются. MCP-серверы stateless — соединение на вызов.
"""

from typing import Any, Literal, Protocol

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from app.config import Settings
from app.security.agent_context import HEADER_NAME

Server = Literal["kb", "crm", "docs"]


class ToolCallError(Exception):
    """Инструмент вернул ошибку или недоступен."""


class ToolCaller(Protocol):
    async def call(self, server: Server, tool: str, args: dict[str, Any], context: str) -> Any: ...


class McpToolClient:
    def __init__(self, settings: Settings, timeout_s: float = 15.0) -> None:
        self._urls: dict[Server, str] = {
            "kb": str(settings.kb_mcp_url),
            "crm": str(settings.crm_mcp_url),
            "docs": str(settings.docs_mcp_url),
        }
        self._timeout = timeout_s

    async def call(self, server: Server, tool: str, args: dict[str, Any], context: str) -> Any:
        try:
            async with (
                httpx2.AsyncClient(headers={HEADER_NAME: context}, timeout=self._timeout) as http,
                Client(streamable_http_client(self._urls[server], http_client=http)) as client,
            ):
                result = await client.call_tool(tool, args)
        except Exception as exc:
            raise ToolCallError(f"{server}.{tool} unavailable") from exc
        if result.is_error:
            raise ToolCallError(f"{server}.{tool} returned an error")
        content = result.structured_content
        if isinstance(content, dict) and set(content) == {"result"}:
            return content["result"]
        return content
