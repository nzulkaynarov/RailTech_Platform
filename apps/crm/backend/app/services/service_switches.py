"""Выключатели внешних сервисов в процессе (M3-CRM-12, ADR-0024): кто сейчас выключен вручную.

Таблица `external_service_switches` читается с кэшем (по умолчанию 10 с), поэтому выключатель
действует во всех процессах (api, worker, MCP) за время кэша без перезапуска. `peek()` — для
синхронного кода (Langfuse): отдаёт последнее известное значение и обновляет его в фоне.
Сбой БД не роняет вызывающего — действует последнее известное состояние.
"""

import asyncio
import time
from collections.abc import Callable

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.external_services import ExternalServiceSwitch

logger = structlog.get_logger(__name__)


class SwitchBoard:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        ttl_s: float = 10.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._sessions = sessions
        self._ttl_s = ttl_s
        self._clock = clock
        self._disabled: frozenset[str] = frozenset()
        self._expires = 0.0
        self._refreshing: asyncio.Task[frozenset[str]] | None = None

    async def disabled_keys(self) -> frozenset[str]:
        if self._clock() < self._expires:
            return self._disabled
        try:
            async with self._sessions() as session:
                rows = await session.scalars(
                    select(ExternalServiceSwitch.service_key).where(
                        ExternalServiceSwitch.disabled.is_(True)
                    )
                )
                self._disabled = frozenset(rows.all())
        except Exception as exc:  # noqa: BLE001 — выключатель не должен ронять бота и воркер
            logger.warning("service_switches_unavailable", error=type(exc).__name__)
        self._expires = self._clock() + self._ttl_s
        return self._disabled

    async def is_disabled(self, key: str) -> bool:
        return key in await self.disabled_keys()

    def peek(self, key: str) -> bool:
        """Синхронно: последнее известное значение; устаревшее — обновить в фоне."""
        if self._clock() >= self._expires and (self._refreshing is None or self._refreshing.done()):
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
            if loop is not None:
                self._refreshing = loop.create_task(self.disabled_keys())
        return key in self._disabled

    def invalidate(self) -> None:
        self._expires = 0.0
