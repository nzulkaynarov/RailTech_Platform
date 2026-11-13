"""Повторная публикация профиля компании (задача «Н3a2», FIX-42): название и контакты из раздела
«Компания».

ERP держит проекцию из `crm.company_profile.changed` (письма, документы, кабинет). Событие
уходит при сохранении настройки; если ERP не было на шине в тот момент (новая выкладка, сбой
доставки), воркер CRM при каждом старте публикует текущее значение заново — по образцу
`ai_policy_publish.py`. `changed_at` — время сохранения настройки, нет строки — начало эпохи:
проекция применяет снимок не старее уже применённого. Сбой не пробрасывается: старт воркера от
шины не зависит.
"""

from datetime import UTC, datetime
from typing import Final

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bus import events as bus_events
from app.models.leads import Setting
from app.schemas.settings import CompanySettings
from app.security.audit import Actor

logger = structlog.get_logger(__name__)

EPOCH: Final = datetime(1970, 1, 1, tzinfo=UTC)


async def republish_company_profile(sessions: async_sessionmaker[AsyncSession]) -> str:
    """Опубликовать текущий профиль событием `crm.company_profile.changed`; вернуть название."""
    async with sessions() as session, session.begin():
        row = await session.get(Setting, "company")
        company = CompanySettings.model_validate(row.value) if row else CompanySettings()
        await bus_events.company_profile_changed(
            session,
            company.model_dump(mode="json"),
            Actor.system(),
            changed_at=row.updated_at if row else EPOCH,
        )
    return company.name


async def sync_company_profile_on_start(sessions: async_sessionmaker[AsyncSession]) -> None:
    """Вызов при старте воркера: любой сбой — в лог (`company_profile_republish_failed`)."""
    try:
        name = await republish_company_profile(sessions)
        logger.info("company_profile_republished", name=name)
    except Exception as exc:  # noqa: BLE001 — старт сервиса не зависит от шины
        logger.warning("company_profile_republish_failed", error=repr(exc))
