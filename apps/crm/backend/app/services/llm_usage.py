"""Запись учёта вызовов моделей в `llm_usage` (аудит 2026-10-12 §3 п. 5).

Запись никогда не ломает вызов модели: любая ошибка — предупреждение в лог.
"""

from typing import Literal

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.integrations.litellm_catalog import ModelCatalog
from app.integrations.llm_usage import UsageEvent, current_lead_id
from app.models.system import LlmUsage

logger = structlog.get_logger(__name__)


class DbUsageRecorder:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        catalog: ModelCatalog | None,
        kind: Literal["work", "test"] = "work",
    ) -> None:
        self._sessions = sessions
        self._catalog = catalog
        self._kind = kind

    async def record(self, event: UsageEvent) -> None:
        if event.cost_usd is None:
            logger.warning("llm_usage_cost_missing", alias=event.alias, purpose=event.purpose)
        try:
            provider = await self._catalog.provider(event.alias) if self._catalog else None
            async with self._sessions() as session, session.begin():
                session.add(
                    LlmUsage(
                        purpose=event.purpose,
                        alias=event.alias,
                        provider=provider,
                        model=(event.model or "")[:128] or None,
                        input_tokens=event.input_tokens,
                        output_tokens=event.output_tokens,
                        cost_usd=event.cost_usd or 0.0,
                        lead_id=current_lead_id(),
                        kind=self._kind,
                    )
                )
        except Exception as exc:  # noqa: BLE001 — учёт не должен ронять ответ клиенту
            logger.warning("llm_usage_record_failed", alias=event.alias, error=type(exc).__name__)
