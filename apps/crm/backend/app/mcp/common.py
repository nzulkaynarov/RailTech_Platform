"""Общее для MCP-серверов: проверка контекста агента и HTTP-приложение (SPEC §7.1)."""

from collections.abc import Mapping
from typing import Any

import uvicorn
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette

from app.config import Settings
from app.security.agent_context import HEADER_NAME, AgentContext, AgentContextError, verify


def header(headers: Mapping[str, str] | None, name: str) -> str | None:
    if not headers:
        return None
    lowered = name.lower()
    return next((v for k, v in headers.items() if k.lower() == lowered), None)


def require_context(ctx: Context[Any, Any], settings: Settings) -> AgentContext:
    """Контекст из подписанного заголовка; ошибка — отказ инструмента без деталей."""
    try:
        return verify(header(ctx.headers, HEADER_NAME), settings.agent_context_key_bytes)
    except AgentContextError as exc:
        raise ToolError("agent context rejected") from exc


def build_app(server: MCPServer[Any], service_name: str, port: int) -> Starlette:
    allowed = [f"{service_name}:{port}", f"localhost:{port}", f"127.0.0.1:{port}"]
    return server.streamable_http_app(
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(allowed_hosts=allowed),
        host="0.0.0.0",  # noqa: S104 — слушаем внутри контейнера, наружу порт не публикуется
    )


def serve(app: Starlette, port: int) -> None:
    uvicorn.run(app, host="0.0.0.0", port=port, log_config=None)  # noqa: S104
