"""Langfuse — трейсы LLM, стоимость, датасеты (SPEC §2, §13).

Если ключи не заданы — все функции работают как no-op (dev без профиля
observability). Персональные данные маскируются (`security/pii.py`).

Выключатель «Langfuse» в центре внешних сервисов (ADR-0024): процесс ставит `set_gate()`; пока
сервис выключен вручную, `client()` отдаёт None и трейсы не пишутся.
"""

from collections.abc import Callable, Iterator
from contextlib import contextmanager, nullcontext
from functools import lru_cache
from typing import Any

from app.config import get_settings
from app.security.pii import langfuse_mask


def _never() -> bool:
    return False


_GATE: list[Callable[[], bool]] = [_never]


def set_gate(switched_off: Callable[[], bool]) -> None:
    """Источник «Langfuse выключен вручную» для процесса (контейнер зависимостей)."""
    _GATE[0] = switched_off


def client() -> Any | None:
    lf = _client()
    if lf is None or _GATE[0]():
        return None
    return lf


@lru_cache
def _client() -> Any | None:
    settings = get_settings()
    if not settings.langfuse_public_key or not settings.langfuse_secret_key.get_secret_value():
        return None
    from langfuse import Langfuse

    return Langfuse(
        public_key=settings.langfuse_public_key,
        secret_key=settings.langfuse_secret_key.get_secret_value(),
        base_url=str(settings.langfuse_host),
        environment=settings.app_env,
        mask=langfuse_mask,
    )


@contextmanager
def trace(name: str, *, lead_id: int, mode: str, stage: str, input: Any) -> Iterator[Any]:
    lf = client()
    if lf is None:
        yield None
        return
    from langfuse import propagate_attributes

    with (
        lf.start_as_current_observation(name=name, as_type="agent", input=input) as span,
        propagate_attributes(
            session_id=f"lead-{lead_id}",
            metadata={"lead_id": str(lead_id), "mode": mode, "stage": stage},
            tags=[mode, stage],
        ),
    ):
        yield span


def generation(*, name: str, model: str, input: Any) -> Any:
    lf = client()
    if lf is None:
        return nullcontext(None)
    return lf.start_as_current_observation(
        name=name, as_type="generation", model=model, input=input
    )


def finish_generation(span: Any, output: str, model: str, tokens_in: int, tokens_out: int) -> None:
    if span is None:
        return
    span.update(
        output=output, model=model, usage_details={"input": tokens_in, "output": tokens_out}
    )


def current_trace_id() -> str | None:
    lf = client()
    if lf is None:
        return None
    trace_id: str | None = lf.get_current_trace_id()
    return trace_id
