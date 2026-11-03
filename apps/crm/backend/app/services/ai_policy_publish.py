"""Повторная публикация политики защиты данных для ИИ (PD-BIZ, DECISIONS 2026-11-03).

Политику ведёт CRM (`settings.ai.pii_policy`), EDS держит проекцию из `crm.ai_policy.changed`.
Событие уходит при сохранении настройки, но если EDS не было на шине в тот момент (новая выкладка,
сбой доставки), проекция остаётся без политики и ведёт себя как «Строгая». Поэтому воркер CRM при
каждом старте публикует текущее значение заново — по образцу `eds_rights_republished`
(`identity_catalog.py`) и команды `republish-identity`.

`changed_at` — время сохранения настройки (`settings.updated_at`), а нет сохранённой строки — начало
эпохи: проекция применяет снимок не старее уже применённого, поэтому повтор идемпотентен и более
новую правку не затирает. Сбой не пробрасывается: старт воркера не зависит от шины, повтор — при
следующем старте.
"""

from datetime import UTC, datetime
from typing import Final

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bus import events as bus_events
from app.models.leads import Setting
from app.schemas.settings import AiSettings
from app.security.audit import Actor

logger = structlog.get_logger(__name__)

EPOCH: Final = datetime(1970, 1, 1, tzinfo=UTC)


async def republish_ai_policy(sessions: async_sessionmaker[AsyncSession]) -> str:
    """Опубликовать текущую политику событием `crm.ai_policy.changed`; вернуть её значение."""
    async with sessions() as session, session.begin():
        row = await session.get(Setting, "ai")
        policy = AiSettings.model_validate(row.value).pii_policy if row else AiSettings().pii_policy
        await bus_events.ai_policy_changed(
            session, policy, Actor.system(), changed_at=row.updated_at if row else EPOCH
        )
    return policy


async def sync_ai_policy_on_start(sessions: async_sessionmaker[AsyncSession]) -> None:
    """Вызов при старте воркера: любой сбой — в лог (`ai_policy_republish_failed`)."""
    try:
        policy = await republish_ai_policy(sessions)
        logger.info("ai_policy_republished", pii_policy=policy)
    except Exception as exc:  # noqa: BLE001 — старт сервиса не зависит от шины
        logger.warning("ai_policy_republish_failed", error=repr(exc))
