"""erp-mcp на официальном SDK `mcp` (FIX-36, S-12): отдельный процесс, не часть Daphne/ASGI-приложения Django.

Тот же каркас, что у серверов CRM (`apps/crm/backend/app/mcp/common.py`): `MCPServer`, streamable HTTP,
stateless + JSON-ответы, внутренний порт (наружу не публикуется; Caddy отдаёт `/mcp` снаружи 404 — FIX-03).

Отличия от CRM, продиктованные контрактом `packages/contracts/mcp-tools.json`:
- состав инструментов, описания и схемы аргументов берутся из контракта, а не из подписей функций: сервер
  переопределяет `list_tools` и `call_tool` (публичные методы `MCPServer`) и не регистрирует инструментов в коде;
- контекст агента проверяет `AgentContextGate` (401/429/400 по контракту, одноразовость `jti`); сам вызов проверяет
  контекст ещё раз — инструмент не зависит от того, что вратарь стоит перед ним;
- обработчики используют синхронный Django ORM и выполняются через `sync_to_async` (процесс делает `django.setup()`);
- ни текст исключения, ни трассировка к модели не уходят: известные отказы — коды `TOOL_NOT_AVAILABLE_IN_MODE`,
  `TOOL_EXECUTION_ERROR` (текст пишет код обработчика), всё остальное — `INTERNAL_ERROR` без подробностей.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Final

import uvicorn
from asgiref.sync import sync_to_async
from django.db import close_old_connections, connection
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from mcp_types import CallToolResult, TextContent
from mcp_types import Tool as MCPTool
from starlette.types import ASGIApp

from .context import HEADER_NAME, AgentContext, AgentContextError
from .contract import ToolsContract, ToolSpec, load_contract
from .gate import AgentContextGate, argument_errors, verify_header
from .tools import ToolExecutionError, ToolModeError, assert_handlers_match_contract, execute_tool

logger = logging.getLogger(__name__)

SERVICE: Final = "erp-mcp"
PORT: Final = int(os.environ.get("ERP_MCP_PORT", "8104"))

INSTRUCTIONS: Final = (
    "Данные клиента в ERP: сделки, документы, поставки, каталог, заявки. Клиент — из подписанного контекста."
)


def _error(code: str, message: str | None = None) -> CallToolResult:
    text = f"{code}: {message}" if message else code
    structured: dict[str, Any] = {"error": code}
    if message:
        structured["message"] = message
    return CallToolResult(content=[TextContent(type="text", text=text)], structured_content=structured, is_error=True)


def _success(data: Any) -> CallToolResult:
    text = json.dumps(data, ensure_ascii=False, default=str)
    return CallToolResult(
        content=[TextContent(type="text", text=text)],
        structured_content={"result": json.loads(text)},
        is_error=False,
    )


def _close_stale_connections() -> None:
    # В транзакции (тесты pytest-django) соединение закрывать нельзя — это снесло бы тестовую транзакцию.
    if not connection.in_atomic_block:
        close_old_connections()


def _run_tool(agent: AgentContext, spec: ToolSpec, arguments: dict[str, Any]) -> CallToolResult:
    _close_stale_connections()
    try:
        return _success(execute_tool(agent, spec, arguments))
    except ToolModeError as exc:
        return _error("TOOL_NOT_AVAILABLE_IN_MODE", str(exc))
    except ToolExecutionError as exc:
        return _error("TOOL_EXECUTION_ERROR", str(exc))
    except Exception:
        logger.exception("erp-mcp: tool %s crashed", spec.name)  # подробности — в журнал процесса, не модели
        return _error("INTERNAL_ERROR")
    finally:
        _close_stale_connections()


class ErpMcpServer(MCPServer[Any]):
    """`MCPServer`, чьи инструменты задаёт контракт `mcp-tools.json`."""

    def __init__(self, contract: ToolsContract) -> None:
        super().__init__(SERVICE, instructions=INSTRUCTIONS, version=contract.version)
        self.contract = contract

    async def list_tools(self) -> list[MCPTool]:
        return [
            MCPTool(name=spec.name, description=spec.description, input_schema=spec.input_schema)
            for spec in self.contract.tools.values()
        ]

    async def call_tool(
        self, name: str, arguments: dict[str, Any], context: Context[Any, Any] | None = None
    ) -> CallToolResult:
        spec = self.contract.tools.get(name)
        if spec is None:
            return _error("TOOL_NOT_FOUND")
        headers = context.headers if context is not None else None
        try:
            agent = verify_header(
                next((v for k, v in (headers or {}).items() if k.lower() == HEADER_NAME.lower()), None)
            )
        except AgentContextError:
            return _error("INVALID_AGENT_CONTEXT")
        if argument_errors(spec.input_schema, arguments):
            return _error("INVALID_ARGUMENTS")
        return await sync_to_async(_run_tool, thread_sensitive=True)(agent, spec, arguments)


def create_server(contract: ToolsContract | None = None) -> ErpMcpServer:
    contract = contract or load_contract()
    assert_handlers_match_contract(contract.tools)
    return ErpMcpServer(contract)


def build_app(contract: ToolsContract | None = None, port: int = PORT) -> ASGIApp:
    contract = contract or load_contract()
    server = create_server(contract)
    allowed = [f"{SERVICE}:{port}", f"localhost:{port}", f"127.0.0.1:{port}"]
    app = server.streamable_http_app(
        streamable_http_path=contract.path,
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(allowed_hosts=allowed),
        host="0.0.0.0",  # noqa: S104 — слушаем внутри контейнера, наружу порт не публикуется
    )
    return AgentContextGate(app, contract)


def main() -> None:
    """Запуск uvicorn; Django к этому моменту уже настроен (`python -m integration.mcp`, `__main__.py`)."""
    app = build_app()
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_config=None)  # noqa: S104
