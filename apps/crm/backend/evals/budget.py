"""Потолок расходов на прогон evals: каждый вызов модели — реальные деньги.

`EVAL_MAX_USD` (по умолчанию $1) — фактическая стоимость из заголовка LiteLLM
`x-litellm-response-cost`; вызов без стоимости считается по `UNKNOWN_CALL_USD`
(с запасом). Дошли до потолка — остальные кейсы пропускаются, итоговая проверка
красная с понятной причиной. `EVAL_CASES` — прогнать только перечисленные id.
"""

import os
from collections.abc import Sequence
from typing import Final, Protocol

import pytest

MAX_USD: Final = float(os.environ.get("EVAL_MAX_USD", "1.0"))
UNKNOWN_CALL_USD: Final = 0.02
_spent = [0.0]
_skipped = [0]


class _Case(Protocol):
    @property
    def id(self) -> str: ...


def add(*costs: float | None) -> None:
    _spent[0] += sum(UNKNOWN_CALL_USD if c is None else c for c in costs)


def spent() -> float:
    return _spent[0]


def exhausted() -> bool:
    """Прогон неполный: хотя бы один кейс пропущен из-за потолка."""
    return _skipped[0] > 0


def guard() -> None:
    """Перед платным кейсом: потолок достигнут — кейс не запускается."""
    if _spent[0] >= MAX_USD:
        _skipped[0] += 1
        pytest.skip(f"лимит расходов evals ${MAX_USD:.2f} исчерпан (потрачено ${spent():.2f})")


def selected[C: _Case](cases: Sequence[C]) -> list[C]:
    """`EVAL_CASES=id1,id2` — только эти кейсы (make eval-quick)."""
    wanted = {i.strip() for i in os.environ.get("EVAL_CASES", "").split(",") if i.strip()}
    return [c for c in cases if not wanted or c.id in wanted]
