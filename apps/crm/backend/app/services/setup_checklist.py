"""Чек-лист «Настройка CRM» на главной админа (scope-аудит §3 п. 9, §4).

Бот и модели — из тех же проверок, что и «Состояние системы» (`SystemStatusService`):
бот готов, только если принимает сообщения; модели — по состоянию монитора `model:*`.
Платных вызовов здесь нет.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.system_status import Component
from app.models.auth import User
from app.models.kb import KbDocument
from app.models.leads import Message, Setting

LINKS: dict[str, str] = {
    "company": "/settings?section=company",
    "business_hours": "/settings?section=business_hours",
    "models": "/models",
    "bot": "/integrations",
    "channel": "/integrations",
    "kb": "/kb",
    "team": "/users",
    "test_dialog": "/leads",
}


@dataclass(frozen=True, slots=True)
class SetupFacts:
    company_saved: bool
    business_hours_saved: bool
    models_ok: bool
    bot_running: bool
    channel_set: bool
    kb_indexed: bool
    teammate_with_telegram: bool
    lead_message_exists: bool


def checklist(facts: SetupFacts) -> list[tuple[str, bool]]:
    """Порядок — как шаги мастера; ключи — контракт с фронтом (`t.setup.checklist`)."""
    return [
        ("company", facts.company_saved),
        ("business_hours", facts.business_hours_saved),
        ("models", facts.models_ok),
        ("bot", facts.bot_running),
        ("channel", facts.channel_set),
        ("kb", facts.kb_indexed),
        ("team", facts.teammate_with_telegram),
        ("test_dialog", facts.lead_message_exists),
    ]


async def saved_settings(session: AsyncSession) -> set[str]:
    return set(await session.scalars(select(Setting.key)))


def health_facts(components: Sequence[Component]) -> tuple[bool, bool]:
    """(модели готовы, бот работает) — по компонентам «Состояния системы».

    Модели готовы: шлюз доступен и ни одна модель не в сбое по монитору (или «Проверить»).
    """
    by_key = {c.key: c for c in components}
    gateway = by_key.get("litellm")
    models = [c for c in components if c.key.startswith("model:")]
    models_ok = (
        gateway is not None and gateway.status == "ok" and all(c.status != "fail" for c in models)
    )
    bot = by_key.get("bot")
    return models_ok, bot is not None and bot.status == "ok"


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
