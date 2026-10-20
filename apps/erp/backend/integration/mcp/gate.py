"""Вход erp-mcp: ASGI-вратарь перед приложением официального SDK (CONTRACTS §5, FIX-36).

SDK отдаёт протокол MCP (initialize, tools/list, tools/call, ошибки протокола), а контракт erp-mcp добавляет к HTTP
правила, которых в SDK нет и которые не должны жить внутри инструментов:
- заголовок `X-Agent-Context` проверяется на КАЖДОМ запросе (подпись, типы, срок) — иначе 401 `INVALID_AGENT_CONTEXT`;
- лимит частоты — на компанию из контекста (в режиме prospect — на `crm_client_id`), невалидный контекст считается по
  IP отправителя, чтобы подбор подписи не был бесплатным — 429 + `Retry-After`;
- `jti` одноразовый: гасится на `tools/call` (initialize, ping и tools/list шлёт тот же клиент тем же заголовком) —
  повтор: 401 `INVALID_AGENT_CONTEXT`;
- аргументы `tools/call` проверяются по `input_schema` из `mcp-tools.json` до запуска обработчика — 400 `INVALID_ARGUMENTS`.
Порядок как до FIX-36: лимит → контекст → одноразовость `jti` → аргументы. Тело запроса читается один раз и
передаётся SDK без изменений.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Final

from asgiref.sync import sync_to_async
from django.conf import settings
from jsonschema import Draft202012Validator, FormatChecker
from rest_framework.throttling import SimpleRateThrottle
from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .context import HEADER_NAME, AgentContext, AgentContextError, mark_used, verify_agent_context
from .contract import ToolsContract

logger = logging.getLogger(__name__)

MAX_BODY_BYTES: Final = 1024 * 1024
MAX_ERROR_TEXT: Final = 200
MAX_ERRORS: Final = 10


class BodyTooLarge(Exception):
    pass


class McpRateThrottle(SimpleRateThrottle):
    """Ставка `mcp` из `REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]`; ключ задаёт вратарь, а не запрос DRF."""

    scope = "mcp"

    def __init__(self, ident: str) -> None:
        self._ident = ident
        super().__init__()

    def get_cache_key(self, request: Any, view: Any) -> str:
        return self.cache_format % {"scope": self.scope, "ident": self._ident}


def verify_header(token: str | None) -> AgentContext:
    secret = settings.ERP_MCP_CONTEXT_KEY
    if not secret:
        raise AgentContextError("ERP_MCP_CONTEXT_KEY is not configured")  # закрыто, а не «без проверки»
    return verify_agent_context(token, secret)


def argument_errors(schema: dict[str, Any], arguments: Any) -> list[str]:
    """Нарушения `input_schema`: путь и правило без значений аргумента (модели возвращать их незачем)."""
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(
        f"{'/'.join(str(p) for p in error.absolute_path) or '<root>'}: {error.validator}"
        for error in validator.iter_errors(arguments)
    )
    return [text[:MAX_ERROR_TEXT] for text in errors[:MAX_ERRORS]]


def _client_ip(scope: Scope) -> str:
    client = scope.get("client")
    return client[0] if client else "unknown"


def _throttle_ident(context: AgentContext | None, scope: Scope) -> str:
    if context is None:
        return f"invalid:{_client_ip(scope)}"
    if context.erp_company_id is not None:
        return f"company:{context.erp_company_id}"
    return f"prospect:{context.crm_client_id}"


def _invalid_context() -> JSONResponse:
    return JSONResponse({"detail": "INVALID_AGENT_CONTEXT"}, status_code=401)


async def _read_body(receive: Receive) -> list[Message]:
    """Все куски тела запроса (для повторной отдачи SDK) с ограничением размера."""
    chunks: list[Message] = []
    size = 0
    while True:
        message = await receive()
        chunks.append(message)
        if message["type"] != "http.request":
            break
        size += len(message.get("body", b""))
        if size > MAX_BODY_BYTES:
            raise BodyTooLarge
        if not message.get("more_body", False):
            break
    return chunks


def _replay(chunks: list[Message], receive: Receive) -> Receive:
    pending = list(chunks)

    async def replayed() -> Message:
        if pending:
            return pending.pop(0)
        return await receive()

    return replayed


def _tool_calls(chunks: list[Message]) -> list[dict[str, Any]] | None:
    """Сообщения `tools/call` в теле; `None` — тело не JSON-RPC, пусть отвечает SDK (ошибка разбора)."""
    raw = b"".join(c.get("body", b"") for c in chunks if c["type"] == "http.request")
    try:
        parsed = json.loads(raw.decode("utf-8")) if raw else None
    except (UnicodeDecodeError, ValueError):
        return None
    messages = parsed if isinstance(parsed, list) else [parsed]
    return [m for m in messages if isinstance(m, dict) and m.get("method") == "tools/call"]


class AgentContextGate:
    def __init__(self, app: ASGIApp, contract: ToolsContract) -> None:
        self.app = app
        self.contract = contract

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        token = Headers(scope=scope).get(HEADER_NAME)
        try:
            context: AgentContext | None = verify_header(token)
        except AgentContextError as exc:
            logger.warning("erp-mcp: context rejected (%s)", exc)
            context = None

        throttle = McpRateThrottle(_throttle_ident(context, scope))
        if not await sync_to_async(throttle.allow_request, thread_sensitive=False)(None, None):
            wait = throttle.wait()
            headers = {"Retry-After": str(int(wait) + 1)} if wait else None
            response = JSONResponse({"detail": "TOO_MANY_REQUESTS"}, status_code=429, headers=headers)
            await response(scope, receive, send)
            return
        if context is None:
            await _invalid_context()(scope, receive, send)
            return

        if scope["method"] == "POST":
            try:
                chunks = await _read_body(receive)
            except BodyTooLarge:
                await JSONResponse({"detail": "REQUEST_TOO_LARGE"}, status_code=413)(scope, receive, send)
                return
            rejection = await self._check_tool_calls(context, chunks)
            if rejection is not None:
                await rejection(scope, receive, send)
                return
            receive = _replay(chunks, receive)

        await self.app(scope, receive, send)

    async def _check_tool_calls(self, context: AgentContext, chunks: list[Message]) -> JSONResponse | None:
        calls = _tool_calls(chunks)
        if not calls:
            return None
        try:
            await sync_to_async(mark_used, thread_sensitive=False)(context)
        except AgentContextError as exc:
            logger.warning("erp-mcp: tools/call rejected (%s)", exc)
            return _invalid_context()
        for call in calls:
            params = call.get("params") if isinstance(call.get("params"), dict) else {}
            spec = self.contract.tools.get(str(params.get("name")))
            if spec is None:
                continue  # неизвестный инструмент — ответ SDK/сервера, схемы для проверки нет
            errors = argument_errors(spec.input_schema, params.get("arguments") or {})
            if errors:
                return JSONResponse(
                    {
                        "detail": "INVALID_ARGUMENTS",
                        "jsonrpc": "2.0",
                        "id": call.get("id"),
                        "error": {"code": -32602, "message": "INVALID_ARGUMENTS", "data": errors},
                    },
                    status_code=400,
                )
        return None
