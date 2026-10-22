"""Общий HTTP-транспорт клиентов ERP: один `httpx.AsyncClient` на процесс и `X-Request-ID` (S0-6).

Все HTTP-вызовы CRM -> ERP (`/api/integration/v1/*`, `/health`, сопряжение) идут через `send`:
- клиент создаётся лениво один раз и живёт, пока жив процесс (`Container.aclose()` закрывает его
  в API и воркере): пул соединений и keep-alive вместо нового клиента на каждый вызов;
- таймаут задаётся на вызов (10 с у интеграции и сопряжения, 5 с у пробы `/health`), не на клиент;
- заголовок `X-Request-ID` - идентификатор текущего запроса CRM (его ставит
  `CorrelationIdMiddleware` из заголовка Caddy); вне запроса (воркер очереди) - новый UUID на вызов.
  Идентификатор пишется в журнал CRM рядом с вызовом (`erp_http_call`), по нему вызов находят
  в журнале ERP. Проброс через очереди и события - волна 11 (`correlationid` в конверте).
Секреты и тела запросов не логируются: только метод, путь, статус и длительность.
"""

import asyncio
import time
import uuid
from urllib.parse import urlsplit

import httpx
import structlog
from asgi_correlation_id import correlation_id

REQUEST_ID_HEADER = "X-Request-ID"

logger = structlog.get_logger(__name__)


class SharedAsyncClient:
    """Ленивый общий `httpx.AsyncClient`: создаётся при первом вызове, пересоздаётся после закрытия.

    Клиент привязан к циклу событий, в котором создан: если цикл сменился (тесты, повторный
    `asyncio.run`), берётся новый - старый нельзя закрыть из чужого цикла.
    """

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    def get(self) -> httpx.AsyncClient:
        loop = asyncio.get_running_loop()
        if self._client is None or self._client.is_closed or self._loop is not loop:
            # Таймаут задаётся на вызов (`send`); на клиенте — только запретить «без таймаута».
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(10.0))
            self._loop = loop
        return self._client

    async def aclose(self) -> None:
        client, self._client = self._client, None
        if client is not None and not client.is_closed:
            await client.aclose()


def outgoing_request_id() -> str:
    """Идентификатор текущего запроса CRM или новый UUID, если вызов идёт вне запроса (воркер)."""
    return correlation_id.get() or str(uuid.uuid4())


async def send(
    shared: SharedAsyncClient,
    method: str,
    url: str,
    *,
    timeout_s: float,
    headers: dict[str, str],
    json: object | None = None,
    content: bytes | None = None,
) -> httpx.Response:
    """Один вызов ERP общим клиентом с `X-Request-ID` и строкой в журнале CRM."""
    request_id = outgoing_request_id()
    path = urlsplit(url).path
    started = time.monotonic()
    try:
        response = await shared.get().request(
            method,
            url,
            json=json,
            content=content,
            headers={**headers, REQUEST_ID_HEADER: request_id},
            timeout=timeout_s,
        )
    except Exception as exc:
        logger.warning(
            "erp_http_call",
            method=method,
            path=path,
            request_id=request_id,
            error=type(exc).__name__,
            duration_ms=int((time.monotonic() - started) * 1000),
        )
        raise
    logger.info(
        "erp_http_call",
        method=method,
        path=path,
        request_id=request_id,
        status=response.status_code,
        duration_ms=int((time.monotonic() - started) * 1000),
    )
    return response
