"""Регистрация обработчиков: `@subscribe("uz.railtech.erp.quote.sent.v1")` или маска `uz.railtech.erp.*.v1`.

Сигнатура обработчика задаётся адаптером: SQLAlchemy — `async def h(event, session)`, Django — `def h(event)`,
память (BFF) — `async def h(event)`. Тип без обработчика (или версия выше поддерживаемой: обработчик `….v1`,
пришло `….v2`) — запись inbox `skipped`, ответ 200.

`inline=True` — обработчик выполняется в запросе приёмника, до ответа, с полным событием (секретные поля не
замаскированы); ошибка — откат записи inbox и 503 (издатель повторит). Остальные — в очереди сервиса по записи inbox.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from fnmatch import fnmatchcase
from typing import Any

_PATTERN_RE = re.compile(r"^uz\.railtech\.[a-z0-9_.*?\[\]-]+\.v[0-9*]+$")


@dataclass(frozen=True)
class Handler:
    pattern: str
    func: Callable[..., Any]
    inline: bool = False

    @property
    def name(self) -> str:
        return f"{getattr(self.func, '__module__', '?')}.{getattr(self.func, '__qualname__', repr(self.func))}"


class HandlerRegistry:
    """Набор обработчиков сервиса; порядок вызова — порядок регистрации."""

    def __init__(self) -> None:
        self._handlers: list[Handler] = []

    def add(self, pattern: str, func: Callable[..., Any], *, inline: bool = False) -> None:
        if not _PATTERN_RE.match(pattern):
            raise ValueError(f"handler pattern {pattern!r} must be uz.railtech.<…>.v<N> (fnmatch mask)")
        self._handlers.append(Handler(pattern, func, inline))

    def subscribe[F: Callable[..., Any]](self, pattern: str, *, inline: bool = False) -> Callable[[F], F]:
        def decorator(func: F) -> F:
            self.add(pattern, func, inline=inline)
            return func

        return decorator

    def match(self, event_type: str) -> list[Handler]:
        return [h for h in self._handlers if fnmatchcase(event_type, h.pattern)]

    def clear(self) -> None:
        self._handlers.clear()

    def __len__(self) -> int:
        return len(self._handlers)


#: Реестр по умолчанию: `rt_bus.subscribe` пишет сюда, адаптеры берут его, если не передан свой.
default_registry = HandlerRegistry()


def subscribe[F: Callable[..., Any]](pattern: str, *, inline: bool = False) -> Callable[[F], F]:
    """`@rt_bus.subscribe("uz.railtech.crm.client.updated.v1")` — регистрация в реестре по умолчанию."""
    return default_registry.subscribe(pattern, inline=inline)
