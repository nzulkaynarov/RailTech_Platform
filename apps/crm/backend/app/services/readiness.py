"""Проверка готовности (`GET /ready`): зависимости, без которых api не работает.

Проверки выполняются параллельно, каждая со своим таймаутом. Детали ошибок
пишутся в лог, наружу отдаётся только `ok`/`fail` по каждой зависимости.
"""

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass

import structlog

Probe = Callable[[], Awaitable[None]]

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class ReadinessReport:
    checks: Mapping[str, bool]

    @property
    def ok(self) -> bool:
        return all(self.checks.values())


class ReadinessService:
    def __init__(self, probes: Mapping[str, Probe], timeout_s: float) -> None:
        self._probes = dict(probes)
        self._timeout_s = timeout_s

    async def check(self) -> ReadinessReport:
        names = list(self._probes)
        results = await asyncio.gather(*(self._run(name) for name in names))
        return ReadinessReport(checks=dict(zip(names, results, strict=True)))

    async def _run(self, name: str) -> bool:
        try:
            await asyncio.wait_for(self._probes[name](), timeout=self._timeout_s)
        except Exception as exc:  # noqa: BLE001 — любая ошибка зависимости = not ready
            logger.warning("readiness_check_failed", check=name, error=repr(exc))
            return False
        return True
