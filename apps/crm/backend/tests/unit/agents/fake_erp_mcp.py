"""Подставной транспорт `erp-mcp` для unit-тестов: настоящий SDK `mcp` поверх `MockTransport`.

Отвечает на JSON-RPC так, как сервер в JSON-режиме (`stateless_http`, `json_response`); поведение
вратаря (401/429/400, сбой сети) задаётся через `reject` и `reject_always`.
"""

import json
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx2

from app.security.erp_agent_context import HEADER_NAME

ToolHandler = Callable[[str, dict[str, Any]], dict[str, Any]]
CONTRACT = Path(__file__).resolve().parents[6] / "packages" / "contracts" / "mcp-tools.json"


def contract_tools() -> list[dict[str, Any]]:
    """Инструменты как их отдаёт сервер: имя, описание и схема аргументов — из контракта."""
    tools = json.loads(CONTRACT.read_text(encoding="utf-8"))["tools"]
    return [
        {"name": t["name"], "description": t["description"], "inputSchema": t["input_schema"]}
        for t in tools
    ]


def tool_ok(data: Any) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False)}],
        "structuredContent": {"result": data},
        "isError": False,
    }


def tool_error(code: str) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": code}],
        "structuredContent": {"error": code},
        "isError": True,
    }


class FakeErpMcp:
    """`reject(...)` — отказ вратаря на ближайший запрос (`on` — только этого метода JSON-RPC,
    иначе любого), `reject_always(...)` — на все. `tool_calls` — дошедшие до инструмента вызовы."""

    def __init__(self, handler: ToolHandler | None = None) -> None:
        self.gate: deque[tuple[str | None, httpx2.Response | Exception]] = deque()
        self.always: tuple[str | None, httpx2.Response | Exception] | None = None
        self.handler = handler or (lambda name, args: tool_ok([]))
        self.contexts: list[str] = []
        self.methods: list[str] = []
        self.request_ids: list[str] = []
        self.tool_calls: list[tuple[str, dict[str, Any]]] = []

    def reject(
        self, outcome: httpx2.Response | Exception, *, on: str | None = None, times: int = 1
    ) -> None:
        self.gate.extend([(on, outcome)] * times)

    def reject_always(self, outcome: httpx2.Response | Exception, *, on: str | None = None) -> None:
        self.always = (on, outcome)

    @property
    def transport(self) -> httpx2.MockTransport:
        return httpx2.MockTransport(self._respond)

    def _respond(self, request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content or b"{}")
        method = str(body.get("method"))
        self.contexts.append(request.headers.get(HEADER_NAME.lower(), ""))
        self.methods.append(method)
        self.request_ids.append(request.headers.get("x-request-id", ""))
        outcome = self._gate_outcome(method)
        if isinstance(outcome, Exception):
            raise outcome
        if outcome is not None:
            return outcome
        if method == "initialize":
            return self._result(
                body,
                {
                    "protocolVersion": body["params"]["protocolVersion"],
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "erp-mcp", "version": "0.1.0"},
                },
            )
        if method == "tools/list":
            return self._result(body, {"tools": contract_tools()})
        if method == "tools/call":
            name, args = body["params"]["name"], body["params"].get("arguments") or {}
            self.tool_calls.append((name, args))
            return self._result(body, self.handler(name, args))
        if "id" not in body:
            return httpx2.Response(202)
        error = {"code": -32601, "message": "Method not found"}
        return httpx2.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "error": error})

    def _gate_outcome(self, method: str) -> httpx2.Response | Exception | None:
        if self.always and self.always[0] in (None, method):
            return self.always[1]
        for index, (on, outcome) in enumerate(self.gate):
            if on in (None, method):
                del self.gate[index]
                return outcome
        return None

    @staticmethod
    def _result(body: dict[str, Any], result: dict[str, Any]) -> httpx2.Response:
        return httpx2.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": result})


def rejection(status: int, detail: str, **headers: str) -> httpx2.Response:
    return httpx2.Response(status, json={"detail": detail}, headers=headers)
