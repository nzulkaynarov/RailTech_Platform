"""Клиент `erp-mcp`: инструменты ERP для сервисного режима бота (CONTRACTS §5, Q-FIX36-1).

Отличия от `McpToolClient` (kb/crm/docs):
- контекст `X-Agent-Context` выпускается заново на каждую попытку (новый `jti`, ERP принимает
  его один раз); клиент и компания — только из `ErpScope`, который собирает код, а не модель;
- SDK `mcp` не отдаёт код HTTP-ответа: на 401/400/429 вратаря (`integration/mcp/gate.py`)
  исключение транспорта одно и то же — `MCPError(-32603, "Server returned an error response")`.
  Поэтому статус и `Retry-After` берутся из `event_hooks` HTTP-клиента, а не из текста исключения;
- политика (Q-FIX36-1, вариант 1): 401 — один повтор с новым контекстом; 429 — ждать
  `Retry-After` (не дольше `max_wait_s`, не больше `rate_retries` раз), затем отказ; 400 и
  сетевой сбой — отказ без повтора;
- любой отказ — `ErpMcpError(kind)`: агент отвечает честно («сейчас не могу проверить»).
"""

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Final, Literal, Protocol

import httpx2
import structlog
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from app.integrations.erp_transport import REQUEST_ID_HEADER, outgoing_request_id
from app.security.erp_agent_context import HEADER_NAME, ErpScope, issue_erp_context

logger = structlog.get_logger(__name__)

Kind = Literal["unavailable", "rate_limited", "context_rejected", "invalid_arguments", "tool_error"]

DEFAULT_RETRY_AFTER_S: Final = 1.0
# Коды результата инструмента (is_error), которые значат то же, что HTTP-отказ вратаря.
_RESULT_KINDS: Final[dict[str, Kind]] = {
    "INVALID_AGENT_CONTEXT": "context_rejected",
    "INVALID_ARGUMENTS": "invalid_arguments",
}


class ErpMcpError(Exception):
    """Данные ERP получить не удалось; `kind` — причина для журнала, текст клиенту решает агент."""

    def __init__(self, kind: Kind, tool: str, code: str | None = None) -> None:
        super().__init__(f"erp.{tool}: {kind}" + (f" ({code})" if code else ""))
        self.kind = kind
        self.tool = tool
        self.code = code


class ErpToolCaller(Protocol):
    async def call(self, tool: str, args: dict[str, Any], scope: ErpScope) -> Any: ...


@dataclass(slots=True)
class _Rejection:
    """Первый отказ вратаря `erp-mcp` за попытку: код HTTP и `Retry-After`."""

    status: int | None = None
    retry_after_s: float | None = None

    async def on_response(self, response: httpx2.Response) -> None:
        if self.status is not None or response.status_code < 400:
            return
        self.status = response.status_code
        raw = response.headers.get("retry-after", "")
        self.retry_after_s = float(raw) if raw.replace(".", "", 1).isdigit() else None


@dataclass(slots=True)
class _Attempt:
    """Состояние повторов одного вызова: контекст перевыпускается один раз, 429 ждём ограниченно."""

    context_refreshed: bool = False
    rate_waits: int = 0


class ErpMcpClient:
    def __init__(
        self,
        url: str,
        key: bytes,
        *,
        timeout_s: float = 10.0,
        max_wait_s: float = 5.0,
        rate_retries: int = 2,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        transport: httpx2.AsyncBaseTransport | None = None,
        now: Callable[[], float] = time.time,
    ) -> None:
        self._url = url
        self._key = key
        self._timeout = timeout_s
        self._max_wait = max_wait_s
        self._rate_retries = rate_retries
        self._sleep = sleep
        self._transport = transport
        self._now = now

    async def call(self, tool: str, args: dict[str, Any], scope: ErpScope) -> Any:
        state = _Attempt()
        while True:
            rejection = _Rejection()
            try:
                return await self._once(tool, args, scope, rejection)
            except ErpMcpError as exc:
                if exc.kind != "context_rejected":
                    raise
                failure: ErpMcpError = exc
            except Exception as exc:  # noqa: BLE001 — исключения транспорта SDK приходят группами
                failure = self._classify(tool, rejection, exc)
            if not await self._may_retry(failure, rejection, state):
                logger.warning(
                    "erp_mcp_call_failed", tool=tool, kind=failure.kind, code=failure.code
                )
                raise failure

    async def _once(
        self, tool: str, args: dict[str, Any], scope: ErpScope, rejection: _Rejection
    ) -> Any:
        context = issue_erp_context(self._key, scope, now=self._now)
        async with (
            httpx2.AsyncClient(
                headers={HEADER_NAME: context, REQUEST_ID_HEADER: outgoing_request_id()},
                timeout=self._timeout,
                transport=self._transport,
                event_hooks={"response": [rejection.on_response]},
            ) as http,
            Client(streamable_http_client(self._url, http_client=http)) as client,
        ):
            result = await client.call_tool(tool, args)
        if result.is_error:
            structured = result.structured_content
            code = str(structured.get("error")) if isinstance(structured, dict) else None
            raise ErpMcpError(_RESULT_KINDS.get(code or "", "tool_error"), tool, code)
        content = result.structured_content
        if isinstance(content, dict) and set(content) == {"result"}:
            return content["result"]
        return content

    @staticmethod
    def _classify(tool: str, rejection: _Rejection, exc: Exception) -> ErpMcpError:
        if rejection.status == 401:
            return ErpMcpError("context_rejected", tool, "HTTP_401")
        if rejection.status == 429:
            return ErpMcpError("rate_limited", tool, "HTTP_429")
        if rejection.status == 400:
            return ErpMcpError("invalid_arguments", tool, "HTTP_400")
        code = f"HTTP_{rejection.status}" if rejection.status else type(exc).__name__
        return ErpMcpError("unavailable", tool, code)

    async def _may_retry(
        self, failure: ErpMcpError, rejection: _Rejection, state: _Attempt
    ) -> bool:
        if failure.kind == "context_rejected" and not state.context_refreshed:
            state.context_refreshed = True  # новый jti: прежний мог быть погашен или просрочен
            return True
        if failure.kind == "rate_limited" and state.rate_waits < self._rate_retries:
            wait = (
                rejection.retry_after_s
                if rejection.retry_after_s is not None
                else DEFAULT_RETRY_AFTER_S
            )
            if wait > self._max_wait:
                return False  # сервер просит ждать дольше, чем может ждать ход бота
            state.rate_waits += 1
            await self._sleep(wait)
            return True
        return False
