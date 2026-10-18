"""ERP MCP Server View (CRM Agent Integration, CONTRACTS §5, M3-ERP-03).

Реализация транспорта streamable-http на эндпоинте /mcp/erp:
- Проверка заголовка X-Agent-Context (HMAC-SHA256, 60 с)
- При отсутствии / неверной подписи / истечении срока -> HTTP 401 {"detail": "UNAUTHORIZED"}
- Протокол JSON-RPC 2.0 (initialize, notifications/initialized, ping, tools/list, tools/call)
- Поддержка официального Python SDK mcp.Client + streamable_http_client
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict

from django.conf import settings
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .context import AgentContextError, verify_agent_context
from .tools import TOOLS_METADATA, ToolExecutionError, ToolModeError, execute_tool

logger = logging.getLogger(__name__)


class ErpMcpView(APIView):
    """MCP streamable-http endpoint для агентов CRM (CONTRACTS §5, packages/contracts/mcp-tools.json)."""

    authentication_classes = []
    permission_classes = [AllowAny]

    def _get_agent_context(self, request):
        token = request.headers.get("X-Agent-Context") or request.META.get("HTTP_X_AGENT_CONTEXT")
        secret = settings.ERP_MCP_CONTEXT_KEY
        if not secret:
            raise AgentContextError("ERP_MCP_CONTEXT_KEY is not configured")
        return verify_agent_context(token, secret)

    def get(self, request, *args, **kwargs):
        """GET /mcp/erp — проверка доступности эндпоинта и валидности контекста."""
        try:
            context = self._get_agent_context(request)
        except AgentContextError as exc:
            logger.warning("MCP GET rejected: %s", exc)
            return Response({"detail": "UNAUTHORIZED"}, status=status.HTTP_401_UNAUTHORIZED)

        return Response(
            {
                "server": "erp-mcp",
                "version": getattr(settings, "ERP_VERSION", "0.1.0"),
                "status": "ok",
                "mode": context.mode,
            },
            status=status.HTTP_200_OK,
        )

    def post(self, request, *args, **kwargs):
        """POST /mcp/erp — обработка JSON-RPC 2.0 сообщений протокола MCP."""
        try:
            context = self._get_agent_context(request)
        except AgentContextError as exc:
            logger.warning("MCP POST rejected: %s", exc)
            return Response({"detail": "UNAUTHORIZED"}, status=status.HTTP_401_UNAUTHORIZED)

        try:
            if isinstance(request.data, dict):
                body = request.data
            else:
                body = json.loads(request.body.decode("utf-8") or "{}")
        except Exception as exc:
            logger.warning("MCP invalid JSON: %s", exc)
            return Response(
                {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        method = str(body.get("method") or "").strip()
        req_id = body.get("id")
        params: Dict[str, Any] = body.get("params") or {}

        # 1. initialize
        if method == "initialize":
            server_version = getattr(settings, "ERP_VERSION", "0.1.0")
            return Response(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {
                            "tools": {},
                        },
                        "serverInfo": {
                            "name": "erp-mcp",
                            "version": server_version,
                        },
                    },
                },
                status=status.HTTP_200_OK,
                headers={"Content-Type": "application/json", "mcp-protocol-version": "2024-11-05"},
            )

        # 2. notifications/initialized
        if method == "notifications/initialized":
            return Response(status=status.HTTP_200_OK, headers={"Content-Type": "application/json"})

        # 3. ping
        if method == "ping":
            return Response(
                {"jsonrpc": "2.0", "id": req_id, "result": {}},
                status=status.HTTP_200_OK,
                headers={"Content-Type": "application/json"},
            )

        # 4. tools/list
        if method == "tools/list":
            tools_list = [
                {
                    "name": t["name"],
                    "description": t["description"],
                    "inputSchema": t["inputSchema"],
                }
                for t in TOOLS_METADATA
            ]
            return Response(
                {"jsonrpc": "2.0", "id": req_id, "result": {"tools": tools_list}},
                status=status.HTTP_200_OK,
                headers={"Content-Type": "application/json"},
            )

        # 5. tools/call
        if method == "tools/call":
            tool_name = str(params.get("name") or "").strip()
            arguments = params.get("arguments") or {}
            try:
                result_data = execute_tool(context, tool_name, arguments)
                content_text = json.dumps(result_data, ensure_ascii=False, default=str)
                return Response(
                    {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "result": {
                            "content": [{"type": "text", "text": content_text}],
                            "structuredContent": {"result": result_data},
                            "isError": False,
                        },
                    },
                    status=status.HTTP_200_OK,
                    headers={"Content-Type": "application/json"},
                )
            except ToolModeError as exc:
                return Response(
                    {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "result": {
                            "content": [{"type": "text", "text": str(exc)}],
                            "structuredContent": {"error": "TOOL_NOT_AVAILABLE_IN_MODE", "message": str(exc)},
                            "isError": True,
                        },
                    },
                    status=status.HTTP_200_OK,
                    headers={"Content-Type": "application/json"},
                )
            except ToolExecutionError as exc:
                return Response(
                    {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "result": {
                            "content": [{"type": "text", "text": str(exc)}],
                            "structuredContent": {"error": "TOOL_EXECUTION_ERROR", "message": str(exc)},
                            "isError": True,
                        },
                    },
                    status=status.HTTP_200_OK,
                    headers={"Content-Type": "application/json"},
                )
            except Exception as exc:
                logger.exception("Unexpected error executing MCP tool '%s': %s", tool_name, exc)
                return Response(
                    {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "result": {
                            "content": [{"type": "text", "text": f"Internal tool execution error: {exc}"}],
                            "structuredContent": {"error": "INTERNAL_ERROR"},
                            "isError": True,
                        },
                    },
                    status=status.HTTP_200_OK,
                    headers={"Content-Type": "application/json"},
                )

        # Неизвестный метод
        return Response(
            {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {
                    "code": -32601,
                    "message": f"Method '{method}' not found",
                },
            },
            status=status.HTTP_200_OK,
            headers={"Content-Type": "application/json"},
        )
