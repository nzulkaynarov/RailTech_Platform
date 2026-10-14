"""Контекст текущей ИИ-задачи: к какой задаче и сотруднику относятся вызовы шлюза.

Идентификаторы задаются КОДОМ на границе задачи (Celery `run_ai_job`, импорт Excel), не
моделью и не телом запроса пользователя: `session_id` трейса Langfuse = id задачи, `user` =
id сотрудника-владельца. Вне задачи (shell, evals) контекста нет — шлюз помечает вызов как
`erp-adhoc`. Модуль без I/O.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from decimal import Decimal


@dataclass
class CallTrace:
    """Аккумулятор вызовов одной задачи — пишется в журнал и в итог задачи."""

    session_id: str
    user_id: int | None = None
    job_feature: str = ""
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: Decimal = Decimal("0")
    prompt_versions: dict[str, str] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def add_call(self, *, prompt: str, version: str, usage, error_code: str | None) -> None:
        self.calls += 1
        self.input_tokens += usage.input_tokens
        self.output_tokens += usage.output_tokens
        self.cost_usd += usage.cost_usd or Decimal("0")
        self.prompt_versions[prompt] = version
        if error_code:
            self.errors.append(error_code)


_current: ContextVar[CallTrace | None] = ContextVar("erp_ai_call_trace", default=None)


def current_trace() -> CallTrace | None:
    return _current.get()


@contextmanager
def trace_scope(session_id: str, *, user_id: int | None = None, job_feature: str = "") -> Iterator[CallTrace]:
    """Все вызовы шлюза внутри блока относятся к задаче `session_id` сотрудника `user_id`."""
    trace = CallTrace(session_id=session_id, user_id=user_id, job_feature=job_feature)
    token = _current.set(trace)
    try:
        yield trace
    finally:
        _current.reset(token)
