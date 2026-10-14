"""Журнал расходов LiteLLM по HTTP API (M3-CRM-09): `GET /spend/logs/v2` с мастер-ключом.

Проверено на `ghcr.io/berriai/litellm:v1.105.0` (записанный ответ — `tests/fixtures/litellm/
spend_logs_v2.json`): строка на вызов с `startTime` (UTC), `spend`, `prompt_tokens`,
`completion_tokens`, `model_group` (обслуживший алиас), `request_tags` (наши теги + User-Agent),
`status` (`success`|`failure`). Готовой свёртки «день × тег × тег» у прокси нет: `/spend/tags` и
`/global/spend/tags` считают по одному тегу и округляют `spend` до 4 знаков, поэтому строки
читаются целиком и сворачиваются в коде (`domain/ai_spend`).

Ограничения v2: `start_date`/`end_date` — `YYYY-MM-DD HH:MM:SS` в UTC, оба включительно;
`page_size` ≤ 1000; выборка окна — не больше 10 000 строк (`total_is_capped`). Окно с потолком
делится пополам, пока не уложится (минимум — минута; дальше — признак `truncated`).
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Final

import httpx
import structlog
from pydantic import AnyHttpUrl, SecretStr

logger = structlog.get_logger(__name__)

PATH: Final = "/spend/logs/v2"
PAGE_SIZE: Final = 1000
MAX_PAGES: Final = 10  # 10 000 строк — потолок выборки окна в LiteLLM
MIN_WINDOW: Final = timedelta(minutes=1)
_FORMAT: Final = "%Y-%m-%d %H:%M:%S"


class LiteLLMSpendError(Exception):
    """Прокси недоступен или отказал: статус и безопасный текст (без заголовков запроса)."""

    def __init__(self, status: int | None, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


@dataclass(slots=True)
class SpendLogs:
    rows: list[dict[str, Any]] = field(default_factory=list)
    truncated: bool = False


class LiteLLMSpendLogs:
    def __init__(
        self,
        base_url: AnyHttpUrl,
        master_key: SecretStr,
        timeout_s: float = 15.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base = str(base_url).rstrip("/")
        self._key = master_key
        self._timeout_s = timeout_s
        self._transport = transport

    async def fetch(self, start: datetime, end: datetime) -> SpendLogs:
        """Все строки журнала со `startTime` в [start, end] (UTC; границы — с точностью до секунды).

        Вызывающий отсекает лишнее по точному времени и убирает повторы по `request_id`.
        """
        out = SpendLogs()
        headers = {"Authorization": f"Bearer {self._key.get_secret_value()}"}
        async with httpx.AsyncClient(
            base_url=self._base,
            headers=headers,
            timeout=self._timeout_s,
            transport=self._transport,
        ) as client:
            await self._window(client, start, end, out)
        return out

    async def _window(
        self, client: httpx.AsyncClient, start: datetime, end: datetime, out: SpendLogs
    ) -> None:
        first = await self._page(client, start, end, 1)
        if first.get("total_is_capped") and end - start > MIN_WINDOW:
            middle = start + (end - start) / 2
            await self._window(client, start, middle, out)
            await self._window(client, middle, end, out)
            return
        out.truncated = out.truncated or bool(first.get("total_is_capped"))
        out.rows.extend(_rows(first))
        pages = min(_int(first.get("total_pages")), MAX_PAGES)
        for page in range(2, pages + 1):
            out.rows.extend(_rows(await self._page(client, start, end, page)))

    async def _page(
        self, client: httpx.AsyncClient, start: datetime, end: datetime, page: int
    ) -> Mapping[str, Any]:
        params: dict[str, str | int] = {
            "start_date": start.astimezone(UTC).strftime(_FORMAT),
            # Конец — включительно с точностью до секунды: добираем секунду, лишнее отсечёт код.
            "end_date": (end + timedelta(seconds=1)).astimezone(UTC).strftime(_FORMAT),
            "page": page,
            "page_size": PAGE_SIZE,
            "sort_by": "startTime",
            "sort_order": "asc",
        }
        try:
            response = await client.get(PATH, params=params)
        except httpx.HTTPError as exc:
            logger.warning("litellm_spend_unreachable", error=type(exc).__name__)
            raise LiteLLMSpendError(None, type(exc).__name__) from exc
        if response.status_code >= 400:
            logger.warning("litellm_spend_failed", status=response.status_code)
            raise LiteLLMSpendError(response.status_code, _error_text(response))
        try:
            data = response.json()
        except ValueError as exc:
            raise LiteLLMSpendError(response.status_code, "not json") from exc
        if not isinstance(data, dict):
            raise LiteLLMSpendError(response.status_code, "unexpected payload")
        return data


def _rows(page: Mapping[str, Any]) -> list[dict[str, Any]]:
    data = page.get("data")
    return [row for row in data if isinstance(row, dict)] if isinstance(data, list) else []


def _int(raw: object) -> int:
    return raw if isinstance(raw, int) and not isinstance(raw, bool) else 0


def _error_text(response: httpx.Response) -> str:
    """Только `error.message` прокси; на 401/403 — без текста (в нём хэш переданного ключа)."""
    if response.status_code in (401, 403):
        return "unauthorized"
    try:
        err = response.json().get("error")
    except (ValueError, AttributeError):
        return f"HTTP {response.status_code}"
    message = err.get("message") if isinstance(err, dict) else None
    return str(message)[:200] if message else f"HTTP {response.status_code}"
