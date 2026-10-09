"""Вызов чат-моделей через LiteLLM по алиасам (SPEC §7.1, ADR-0004).

Таймаут 20 с, один ретрай (клиент OpenAI), затем `fallback-model`. Все вызовы
трассируются в Langfuse как generation (если Langfuse настроен).
"""

import json
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

import structlog
from openai import APIError, AsyncOpenAI

from app.integrations import langfuse as lf
from app.integrations.litellm import Alias

logger = structlog.get_logger(__name__)

FALLBACK: Alias = "fallback-model"
# Стоимость вызова, которую LiteLLM Proxy возвращает заголовком ответа.
COST_HEADER = "x-litellm-response-cost"


class LlmUnavailableError(Exception):
    """И основная, и запасная модель недоступны."""


@dataclass(frozen=True, slots=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ChatResult:
    text: str
    model: str
    tokens_in: int
    tokens_out: int
    latency_ms: int
    tool_calls: list[ToolCall] = field(default_factory=list)
    used_fallback: bool = False
    cost_usd: float | None = None


class ChatCompleter(Protocol):
    async def complete(
        self,
        messages: Sequence[dict[str, Any]],
        *,
        tools: Sequence[dict[str, Any]] | None = None,
        response_format: dict[str, Any] | None = None,
        name: str = "llm",
    ) -> "ChatResult": ...


class ChatModel:
    def __init__(self, client: AsyncOpenAI, alias: Alias, max_tokens: int = 1024) -> None:
        self._client = client
        self._alias = alias
        self._max_tokens = max_tokens

    async def complete(
        self,
        messages: Sequence[dict[str, Any]],
        *,
        tools: Sequence[dict[str, Any]] | None = None,
        response_format: dict[str, Any] | None = None,
        name: str = "llm",
    ) -> ChatResult:
        for alias in (self._alias, FALLBACK):
            try:
                return await self._call(alias, messages, tools, response_format, name)
            except APIError as exc:
                # Код и текст ответа провайдера («credit balance is too low», квота) — без них
                # сбой ключей не отличить от сбоя кода; текст короткий, PII маскирует логгер.
                logger.warning(
                    "llm_call_failed",
                    alias=alias,
                    error=type(exc).__name__,
                    status=getattr(exc, "status_code", None),
                    detail=str(exc.message)[:200],
                )
        raise LlmUnavailableError(self._alias)

    async def _call(
        self,
        alias: Alias,
        messages: Sequence[dict[str, Any]],
        tools: Sequence[dict[str, Any]] | None,
        response_format: dict[str, Any] | None,
        name: str,
    ) -> ChatResult:
        kwargs: dict[str, Any] = {
            "model": alias,
            "messages": list(messages),
            "max_tokens": self._max_tokens,
        }
        if tools:
            kwargs["tools"] = list(tools)
        if response_format:
            kwargs["response_format"] = response_format
        started = time.monotonic()
        with lf.generation(name=name, model=alias, input=messages) as span:
            raw = await self._client.chat.completions.with_raw_response.create(**kwargs)
            result = _to_result(
                raw.parse(),
                alias,
                started,
                used_fallback=alias == FALLBACK,
                cost_usd=_cost(raw.headers.get(COST_HEADER)),
            )
            lf.finish_generation(
                span, result.text, result.model, result.tokens_in, result.tokens_out
            )
        return result


def _cost(raw: str | None) -> float | None:
    try:
        return float(raw) if raw else None
    except ValueError:
        return None


def _to_result(
    response: Any, alias: Alias, started: float, *, used_fallback: bool, cost_usd: float | None
) -> ChatResult:
    choice = response.choices[0]
    message = choice.message
    calls = [
        ToolCall(id=c.id, name=c.function.name, arguments=_parse_args(c.function.arguments))
        for c in (message.tool_calls or [])
    ]
    usage = response.usage
    return ChatResult(
        text=(message.content or "").strip(),
        model=getattr(response, "model", None) or alias,
        tokens_in=getattr(usage, "prompt_tokens", 0) or 0,
        tokens_out=getattr(usage, "completion_tokens", 0) or 0,
        latency_ms=int((time.monotonic() - started) * 1000),
        tool_calls=calls,
        used_fallback=used_fallback,
        cost_usd=cost_usd,
    )


def _parse_args(raw: str | None) -> dict[str, Any]:
    try:
        parsed = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}
