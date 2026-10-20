"""Опора тестов erp-mcp (FIX-36): приложение SDK в одном процессе с тестом, без сети.

Сервер асинхронный, ORM синхронный. Тесты — обычные синхронные функции с `django_db` (откат транзакции), поэтому
каждый вызов проходит через `async_to_sync`: обработчики инструментов (`sync_to_async(thread_sensitive=True)`)
тогда выполняются в потоке теста, на его соединении и видят данные, созданные в тесте.
"""

from __future__ import annotations

import json
import socket
import threading
import time
import uuid
from contextlib import asynccontextmanager, contextmanager
from typing import Any, AsyncIterator, Iterator

import httpx2
import uvicorn
from asgiref.sync import async_to_sync
from integration.mcp.context import HEADER_NAME, _b64encode, _sign, issue_agent_context
from integration.mcp.server import PORT, build_app
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

MCP_SECRET = "test-erp-mcp-secret-key"
MCP_PATH = "/mcp/erp"
BASE_URL = f"http://127.0.0.1:{PORT}"
# Что требует транспорт SDK от любого клиента; без него ответ 406 и до нашего кода дело не доходит.
RAW_HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


def make_context_token(
    crm_client_id: int = 10,
    erp_company_id: int | None = 1,
    mode: str = "customer",
    language: str = "ru",
    ttl_s: int = 60,
    secret: str = MCP_SECRET,
    now: float | None = None,
    jti: str | None = None,
) -> str:
    return issue_agent_context(
        key=secret,
        crm_client_id=crm_client_id,
        erp_company_id=erp_company_id,
        mode=mode,
        language=language,
        ttl_s=ttl_s,
        now=now,
        jti=jti,
    )


def forge_context(secret: str = MCP_SECRET, **overrides: Any) -> str:
    """Подписанный контекст с произвольными claims: ключ со значением `None` в overrides удаляет claim."""
    now = int(time.time())
    claims: dict[str, Any] = {
        "crm_client_id": 10,
        "erp_company_id": 1,
        "mode": "customer",
        "language": "ru",
        "iat": now,
        "exp": now + 60,
        "jti": str(uuid.uuid4()),
    }
    for key, value in overrides.items():
        if value is None:
            claims.pop(key, None)
        else:
            claims[key] = value
    payload = _b64encode(json.dumps(claims).encode("utf-8"))
    return f"{payload}.{_sign(payload, secret.encode('utf-8'))}"


@asynccontextmanager
async def mcp_http(token: str | None) -> AsyncIterator[httpx2.AsyncClient]:
    """HTTP-клиент поверх приложения erp-mcp (вратарь + SDK) с запущенным lifespan SDK."""
    gate = build_app()
    starlette_app = gate.app
    headers = {HEADER_NAME: token} if token else {}
    async with starlette_app.router.lifespan_context(starlette_app):
        transport = httpx2.ASGITransport(app=gate, client=("10.0.0.7", 51000))
        async with httpx2.AsyncClient(transport=transport, base_url=BASE_URL, headers=headers, timeout=15) as http:
            yield http


def raw_rpc(token: str | None, method: str, params: dict[str, Any] | None = None, *, request_id: int = 1):
    """Сырой JSON-RPC POST (для проверок вратаря и ошибок протокола)."""

    async def run() -> httpx2.Response:
        async with mcp_http(token) as http:
            body = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}}
            return await http.post(MCP_PATH, json=body, headers=RAW_HEADERS)

    return async_to_sync(run)()


def raw_modern_rpc(token: str | None, method: str, params: dict[str, Any] | None = None):
    """JSON-RPC в формате протокола 2026-07-28 (версия и возможности клиента в `_meta`, заголовки Mcp-*)."""
    from mcp_types import CLIENT_CAPABILITIES_META_KEY, PROTOCOL_VERSION_META_KEY

    version = "2026-07-28"
    body_params = {**(params or {}), "_meta": {PROTOCOL_VERSION_META_KEY: version, CLIENT_CAPABILITIES_META_KEY: {}}}
    headers = {**RAW_HEADERS, "MCP-Protocol-Version": version, "Mcp-Method": method}

    async def run() -> httpx2.Response:
        async with mcp_http(token) as http:
            body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": body_params}
            return await http.post(MCP_PATH, json=body, headers=headers)

    return async_to_sync(run)()


def raw_get(token: str | None):
    async def run() -> httpx2.Response:
        async with mcp_http(token) as http:
            return await http.get(MCP_PATH, headers={"Accept": "text/event-stream"})

    return async_to_sync(run)()


def sdk_call(token: str | None, tool: str, arguments: dict[str, Any] | None = None):
    """Вызов инструмента клиентом SDK: initialize → tools/call одним заголовком (как агент CRM)."""

    async def run():
        async with mcp_http(token) as http:
            async with Client(streamable_http_client(f"{BASE_URL}{MCP_PATH}", http_client=http)) as client:
                return await client.call_tool(tool, arguments or {})

    return async_to_sync(run)()


def sdk_list_tools(token: str | None):
    async def run():
        async with mcp_http(token) as http:
            async with Client(streamable_http_client(f"{BASE_URL}{MCP_PATH}", http_client=http)) as client:
                return await client.list_tools()

    return async_to_sync(run)()


def sdk_handshake(token: str | None) -> tuple[str, str, list[str]]:
    """initialize → list_tools клиентом SDK: (имя сервера, версия, имена инструментов)."""

    async def run():
        async with mcp_http(token) as http:
            async with Client(streamable_http_client(f"{BASE_URL}{MCP_PATH}", http_client=http)) as client:
                info = client.server_info
                listed = await client.list_tools()
                return info.name, info.version, [t.name for t in listed.tools]

    return async_to_sync(run)()


def payload(result: Any) -> Any:
    """Данные инструмента: `structured_content["result"]` (структура ответа erp-mcp)."""
    assert not result.is_error, result.structured_content
    return result.structured_content["result"]


@contextmanager
def tcp_server() -> Iterator[str]:
    """Тот же сервер под настоящим uvicorn на свободном порту: Host-проверка SDK, lifespan, клиент по TCP."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    config = uvicorn.Config(build_app(port=port), host="127.0.0.1", port=port, log_config=None)
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 15
    while not server.started:
        assert thread.is_alive() and time.monotonic() < deadline, "uvicorn не стартовал"
        time.sleep(0.05)
    try:
        yield f"http://127.0.0.1:{port}{MCP_PATH}"
    finally:
        server.should_exit = True
        thread.join(timeout=15)
