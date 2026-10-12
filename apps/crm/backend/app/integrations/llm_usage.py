"""Контракт учёта вызовов моделей: событие, приёмник и лид текущего вызова (без I/O).

Каждый вызов модели (чат и эмбеддинги) сообщает приёмнику `UsageEvent`; приёмник пишет строку
в `llm_usage` (`app/services/llm_usage.py`). Лид — из контекстной переменной, которую ставят
сервисы диалога и квалификатора: идентификатор не приходит от модели (SPEC §1.5).
"""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Literal, Protocol

Purpose = Literal[
    "dialog",
    "qualifier",
    "judge",
    "fallback",
    "embed_query",
    "embed_ingest",
    "probe",
    "test",
    "assist_draft",
    "assist_improve",
]

_current_lead: ContextVar[int | None] = ContextVar("llm_usage_lead_id", default=None)


@dataclass(frozen=True, slots=True)
class UsageEvent:
    purpose: Purpose
    alias: str
    model: str | None
    input_tokens: int
    output_tokens: int
    cost_usd: float | None


# Заголовок LiteLLM со стоимостью вызова — одна константа для чата, эмбеддингов и проверки моделей.
COST_HEADER = "x-litellm-response-cost"


class UsageSink(Protocol):
    async def record(self, event: UsageEvent) -> None: ...


def current_lead_id() -> int | None:
    return _current_lead.get()


@contextmanager
def lead_scope(lead_id: int | None) -> Iterator[None]:
    """Все вызовы моделей внутри блока учитываются на лида `lead_id`."""
    token = _current_lead.set(lead_id)
    try:
        yield
    finally:
        _current_lead.reset(token)


def parse_cost(raw: str | None) -> float | None:
    """Заголовок `x-litellm-response-cost` → USD (пустой/битый → None)."""
    try:
        return float(raw) if raw else None
    except ValueError:
        return None
