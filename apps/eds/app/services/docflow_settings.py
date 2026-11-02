"""Настройки документооборота (EDS-REG): одна строка `docflow_settings`; нет строки — значения по умолчанию."""

from sqlalchemy.ext.asyncio import AsyncSession

from app import clock
from app.ai import gateway
from app.config import Settings
from app.models import DocflowSettings
from app.schemas.ai import DocflowSettings as SettingsOut
from app.services import journal

ROW_ID = 1


async def recognize_scans(session: AsyncSession) -> bool:
    row = await session.get(DocflowSettings, ROW_ID)
    return bool(row and row.recognize_scans)


async def read(session: AsyncSession, settings: Settings) -> SettingsOut:
    return SettingsOut(recognize_scans=await recognize_scans(session), ai_available=gateway.available(settings))


async def update(session: AsyncSession, settings: Settings, *, actor_id: int, recognize: bool) -> SettingsOut:
    row = await session.get(DocflowSettings, ROW_ID, with_for_update=True)
    if row is None:
        row = DocflowSettings(id=ROW_ID)
        session.add(row)
    row.recognize_scans = recognize
    row.updated_by = actor_id
    row.updated_at = clock.now()
    await session.flush()
    await journal.record(
        session, "docflow_settings.updated", by=actor_id, comment=f"recognize_scans={str(recognize).lower()}"
    )
    return SettingsOut(recognize_scans=recognize, ai_available=gateway.available(settings))
