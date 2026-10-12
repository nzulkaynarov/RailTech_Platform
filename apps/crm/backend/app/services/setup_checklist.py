"""Чек-лист «Настройка CRM» на главной админа (scope-аудит §3 п. 9, §4).

Только чтение и бесплатные проверки: модели — пинг шлюза LiteLLM и активные алерты монитора
`model:*` (монитор сам решает, когда звать провайдеров); платных вызовов здесь нет.
"""

from dataclasses import dataclass

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth import User
from app.models.kb import KbDocument
from app.models.leads import Message, Setting
from app.models.system import SystemAlert

LINKS: dict[str, str] = {
    "company": "/settings?section=company",
    "business_hours": "/settings?section=business_hours",
    "models": "/settings?section=budget",
    "bot": "/settings?section=bot",
    "channel": "/settings?section=notifications",
    "kb": "/kb",
    "team": "/users",
    "test_dialog": "/leads",
}


@dataclass(frozen=True, slots=True)
class SetupFacts:
    company_saved: bool
    business_hours_saved: bool
    litellm_ok: bool
    model_alerts: int
    bot_configured: bool
    channel_set: bool
    kb_indexed: bool
    teammate_with_telegram: bool
    lead_message_exists: bool


def checklist(facts: SetupFacts) -> list[tuple[str, bool]]:
    """Порядок — как шаги мастера; ключи — контракт с фронтом (`t.setup.checklist`)."""
    return [
        ("company", facts.company_saved),
        ("business_hours", facts.business_hours_saved),
        ("models", facts.litellm_ok and facts.model_alerts == 0),
        ("bot", facts.bot_configured),
        ("channel", facts.channel_set),
        ("kb", facts.kb_indexed),
        ("team", facts.teammate_with_telegram),
        ("test_dialog", facts.lead_message_exists),
    ]


async def saved_settings(session: AsyncSession) -> set[str]:
    return set(await session.scalars(select(Setting.key)))


async def model_alerts(session: AsyncSession) -> int:
    rows = await session.scalars(
        select(SystemAlert.key).where(
            SystemAlert.active.is_(True), SystemAlert.key.startswith("model:")
        )
    )
    return len(list(rows))


async def kb_indexed(session: AsyncSession) -> bool:
    stmt = select(
        exists().where(KbDocument.is_active.is_(True), KbDocument.ingest_status == "done")
    )
    return bool(await session.scalar(stmt))


async def teammate_with_telegram(session: AsyncSession, me: int) -> bool:
    stmt = select(
        exists().where(User.id != me, User.is_active.is_(True), User.tg_user_id.is_not(None))
    )
    return bool(await session.scalar(stmt))


async def lead_message_exists(session: AsyncSession) -> bool:
    return bool(await session.scalar(select(exists().where(Message.role == "lead"))))
