"""Настройки документооборота (EDS-REG, PD-BIZ): одна строка `docflow_settings`; нет строки — значения по умолчанию.

* `recognize_scans` — читать ли моделью сканы и фото писем (выбор администратора, по умолчанию включено, решение
  владельца 2026-11-03). Действует только при политике «Деловая»: при «Строгой» сканы выключены.
* `pii_policy` — проекция политики защиты данных для ИИ из CRM (событие `crm.ai_policy.changed`): владелец поля — CRM,
  здесь она не правится (ORCHESTRATOR §3 п. 16). Нет события — «Деловая», как по умолчанию в CRM.
"""

from datetime import datetime
from typing import Final

from sqlalchemy.ext.asyncio import AsyncSession

from app import clock
from app.ai import gateway
from app.config import Settings
from app.models import DocflowSettings
from app.schemas.ai import DocflowSettings as SettingsOut
from app.security.pii import DEFAULT_POLICY, PiiPolicy
from app.services import journal

ROW_ID = 1
POLICIES: Final = ("business", "strict")


async def recognize_scans(session: AsyncSession) -> bool:
    """Выбор администратора (нет строки — включено)."""
    row = await session.get(DocflowSettings, ROW_ID)
    return True if row is None else bool(row.recognize_scans)


def _policy(value: str | None) -> PiiPolicy:
    """Колонку держит check-ограничение; всё, что не «Строгая», — «Деловая» (по умолчанию)."""
    return "strict" if value == "strict" else DEFAULT_POLICY


async def pii_policy(session: AsyncSession) -> PiiPolicy:
    row = await session.get(DocflowSettings, ROW_ID)
    return _policy(row.pii_policy if row else None)


async def scans_allowed(session: AsyncSession) -> bool:
    """Сканы и фото уходят в модель: политика «Деловая» и включённая настройка."""
    return await pii_policy(session) == "business" and await recognize_scans(session)


async def read(session: AsyncSession, settings: Settings) -> SettingsOut:
    return SettingsOut(
        recognize_scans=await recognize_scans(session),
        pii_policy=await pii_policy(session),
        ai_available=gateway.available(settings),
    )


async def update(session: AsyncSession, settings: Settings, *, actor_id: int, recognize: bool) -> SettingsOut:
    row = await session.get(DocflowSettings, ROW_ID, with_for_update=True)
    if row is None:
        row = DocflowSettings(id=ROW_ID, pii_policy=DEFAULT_POLICY)
        session.add(row)
    row.recognize_scans = recognize
    row.updated_by = actor_id
    row.updated_at = clock.now()
    await session.flush()
    await journal.record(
        session, "docflow_settings.updated", by=actor_id, comment=f"recognize_scans={str(recognize).lower()}"
    )
    return SettingsOut(
        recognize_scans=recognize,
        pii_policy=_policy(row.pii_policy),
        ai_available=gateway.available(settings),
    )


async def apply_policy(session: AsyncSession, policy: str, *, changed_at: datetime, actor_id: int | None) -> bool:
    """Применить политику из события CRM; `False` — неизвестное значение или у проекции политика новее (повтор,
    опоздавшее событие). Повтор того же события ничего не меняет."""
    if policy not in POLICIES:
        return False
    row = await session.get(DocflowSettings, ROW_ID, with_for_update=True)
    if row is None:
        row = DocflowSettings(id=ROW_ID, recognize_scans=True, pii_policy=policy, pii_policy_at=changed_at)
        session.add(row)
    elif row.pii_policy_at is not None and row.pii_policy_at >= changed_at:
        return False
    else:
        row.pii_policy = policy
        row.pii_policy_at = changed_at
    await session.flush()
    await journal.record(session, "docflow_settings.pii_policy", by=actor_id, comment=f"pii_policy={policy}")
    return True
