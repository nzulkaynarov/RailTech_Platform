"""Контракт учёта вызовов моделей: событие, приёмник и лид текущего вызова (без I/O).

Каждый вызов модели (чат и эмбеддинги) сообщает приёмнику `UsageEvent`; приёмник пишет строку
в `llm_usage` (`app/services/llm_usage.py`). Лид — из контекстной переменной, которую ставят
сервисы диалога и квалификатора: идентификатор не приходит от модели (SPEC §1.5).
"""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from app.domain.ai_spend import call_tags

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

UsageKind = Literal["work", "test"]

# Журнал расходов LiteLLM (M3-CRM-09, ARCHITECTURE §8): каждый вызов несёт теги
# `system=crm`, `feature=<функция>`, `model=<алиас>` в `metadata.tags` тела запроса — прокси
# пишет их в `LiteLLM_SpendLogs.request_tags`, «Расходы» сворачивают по ним (`domain/ai_spend`).
FEATURE_BY_PURPOSE: dict[Purpose, str] = {
    "dialog": "dialog",
    "qualifier": "qualifier",
    "judge": "judge",
    "fallback": "fallback",
    "embed_query": "kb-search",
    "embed_ingest": "kb-ingest",
    "probe": "probe",
    "test": "test",
    "assist_draft": "assist-draft",
    "assist_improve": "assist-improve",
}

_current_lead: ContextVar[int | None] = ContextVar("llm_usage_lead_id", default=None)
_current_kind: ContextVar[UsageKind | None] = ContextVar("llm_usage_kind", default=None)


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


def current_kind() -> UsageKind | None:
    return _current_kind.get()


@contextmanager
def kind_scope(kind: UsageKind) -> Iterator[None]:
    """Вызовы внутри блока учитываются с этим `kind` (песочница бота → `test`), а не по env."""
    token = _current_kind.set(kind)
    try:
        yield
    finally:
        _current_kind.reset(token)


def parse_cost(raw: str | None) -> float | None:
    """Заголовок `x-litellm-response-cost` → USD (пустой/битый → None)."""
    try:
        return float(raw) if raw else None
    except ValueError:
        return None


def gateway_body(purpose: Purpose, alias: str, **extra: Any) -> dict[str, Any]:
    """`extra_body` вызова LiteLLM: теги журнала расходов и параметры прокси."""
    return {"metadata": {"tags": call_tags("crm", FEATURE_BY_PURPOSE[purpose], alias)}, **extra}
