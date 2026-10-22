"""Приёмник без базы данных — для BFF (ADR-0011: у BFF нет своей БД; B5 — подписчик шины для SSE).

Дедупликация по `id` — в памяти процесса (последние `capacity` событий); обработчики (`async def h(event)`) вызываются
сразу, в запросе. Ошибка обработчика — 503, `id` забывается, издатель повторит по расписанию.
"""

from __future__ import annotations

import logging
from collections import OrderedDict
from collections.abc import Mapping

from .context import correlation
from .core import BusConfig, BusCore
from .handlers import HandlerRegistry, default_registry
from .receiver import ReceiveResult, Rejection, log_rejection

logger = logging.getLogger("rt_bus")


class MemoryReceiver:
    def __init__(self, config: BusConfig, *, registry: HandlerRegistry | None = None, capacity: int = 10_000) -> None:
        self.core = BusCore(config)
        self.registry = registry if registry is not None else default_registry
        self.capacity = capacity
        self._seen: OrderedDict[str, str] = OrderedDict()

    async def receive(self, headers: Mapping[str, str], body: bytes) -> ReceiveResult:
        decision = self.core.decide(self.registry, headers, body)
        if isinstance(decision, Rejection):
            log_rejection(decision, headers)
            return decision.result()
        event = decision.event
        if event.id in self._seen:
            return ReceiveResult(200, {"status": "duplicate", "id": event.id})
        self._remember(event.id, decision.status)
        if decision.status == "skipped":
            return ReceiveResult(200, {"status": "skipped", "id": event.id})
        with correlation(event.correlationid, event.traceparent):
            try:
                for handler in [*decision.inline, *decision.queued]:
                    await handler.func(event)
            except Exception:
                self._seen.pop(event.id, None)
                logger.exception("rt_bus_handler_failed", extra={"event_id": event.id, "event_type": event.type})
                return ReceiveResult(503, {"error": "handler_failed"})
        return ReceiveResult(200, {"status": "processed", "id": event.id})

    def _remember(self, event_id: str, status: str) -> None:
        self._seen[event_id] = status
        while len(self._seen) > self.capacity:
            self._seen.popitem(last=False)
