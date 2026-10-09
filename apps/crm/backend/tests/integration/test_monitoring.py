"""Монитор (SPEC §13): алерты с дедупликацией, итоги дня, BudgetGuard на реальной БД."""

import random
from datetime import UTC, datetime, timedelta
from typing import cast

import pytest
from aiogram import Bot
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.cli.sample_dialogs import sample
from app.models.leads import Conversation, Lead, Message
from app.models.system import SystemAlert
from app.services.budget import BudgetGuard
from app.services.monitoring import MonitorService
from app.services.settings import SettingsService
from tests.integration.crm_helpers import FakeSender

pytestmark = pytest.mark.integration
CHANNEL = -100500


async def configure(sessions: async_sessionmaker[AsyncSession], daily_usd: float) -> None:
    svc = SettingsService(sessions, ttl_s=0)
    await svc.update("notifications", {"channel_id": CHANNEL, "duty_user_ids": []}, None)
    await svc.update("budget", {"daily_usd": daily_usd, "fallback_model_enabled": True}, None)


async def spend(sessions: async_sessionmaker[AsyncSession], usd: float) -> None:
    async with sessions() as session, session.begin():
        lead = Lead(display_name="Тест", language="ru")
        session.add(lead)
        await session.flush()
        conversation = Conversation(lead_id=lead.id, tg_chat_id=1)
        session.add(conversation)
        await session.flush()
        session.add(
            Message(
                conversation_id=conversation.id,
                role="bot",
                text="ok",
                meta={"action": "answer", "cost_usd": usd},
            )
        )


async def fail_job(sessions: async_sessionmaker[AsyncSession], task: str) -> None:
    async with sessions() as session, session.begin():
        job = await session.execute(
            text(
                "INSERT INTO procrastinate_jobs (queue_name, task_name, status) "
                "VALUES ('q', :task, 'failed') RETURNING id"
            ),
            {"task": task},
        )
        await session.execute(
            text("INSERT INTO procrastinate_events (job_id, type) VALUES (:id, 'failed')"),
            {"id": job.scalar_one()},
        )


def monitor(
    sessions: async_sessionmaker[AsyncSession], bot: FakeSender, ok: list[bool]
) -> MonitorService:
    async def probe() -> bool:
        return ok[0]

    return MonitorService(sessions, SettingsService(sessions, ttl_s=0), cast(Bot, bot), probe)


async def test_alerts_fire_once_repeat_and_resolve(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    await configure(sessions, daily_usd=1.0)
    await spend(sessions, 0.9)
    await fail_job(sessions, "ingest_kb_document")
    bot, litellm = FakeSender(), [False]
    svc = monitor(sessions, bot, litellm)
    now = datetime.now(UTC)

    first = await svc.check(now)
    assert sorted(first) == [
        "⚠️ Бюджет моделей: $0.90 из $1.00 за сегодня (90%)",
        "⚠️ Задача ingest_kb_document: упала после всех попыток: 1 за последний час",
    ]
    assert await svc.check(now + timedelta(minutes=1)) == []  # дедупликация
    third = await svc.check(now + timedelta(minutes=2))
    assert third == ["⚠️ LiteLLM: шлюз моделей недоступен дольше 2 минут"]  # после 2 минут

    litellm[0] = True
    resolved = await svc.check(now + timedelta(minutes=3))
    assert resolved == ["✅ LiteLLM: в норме"]
    async with sessions() as session:
        row = await session.get(SystemAlert, "litellm_down")
    assert row is not None
    assert (row.active, row.resolved_at is not None) == (False, True)
    assert all(chat == CHANNEL for chat, _ in bot.sent)


async def test_daily_report_and_budget_guard(sessions: async_sessionmaker[AsyncSession]) -> None:
    await configure(sessions, daily_usd=0.5)
    await spend(sessions, 0.75)
    bot = FakeSender()
    report = await monitor(sessions, bot, [True]).daily_report(datetime.now(UTC))
    assert report is not None
    assert "новых лидов: 1" in report
    assert "стоимость моделей: $0.75 из $0.50" in report
    guard = BudgetGuard(sessions, SettingsService(sessions, ttl_s=0))
    assert await guard.fallback_required() is True
    await SettingsService(sessions, ttl_s=0).update(
        "budget", {"daily_usd": 0.5, "fallback_model_enabled": False}, None
    )
    assert (
        await BudgetGuard(sessions, SettingsService(sessions, ttl_s=0)).fallback_required() is False
    )


async def test_sample_dialogs_masks_pii(sessions: async_sessionmaker[AsyncSession]) -> None:
    await spend(sessions, 0.01)
    async with sessions() as session, session.begin():
        conversation = (await session.scalars(select(Conversation))).one()
        session.add(
            Message(conversation_id=conversation.id, role="lead", text="Мой +998 90 123 45 67")
        )
    async with sessions() as session:
        rng = random.Random(1)  # noqa: S311
        items = await sample(session, datetime.now(UTC) - timedelta(days=7), 20, rng, "http://crm")
    assert len(items) == 1
    item = items[0]
    assert item["crm_url"] == f"http://crm/leads/{item['lead_id']}"
    assert [t["role"] for t in item["dialog"]] == ["bot", "lead"]
    assert item["dialog"][1]["text"] == "Мой [number]"
    assert item["label"]["golden"] is False


async def test_model_without_credits_alerts_and_resolves_only_on_probe(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    await configure(sessions, daily_usd=0.0)
    problems: dict[str, str | None] = {
        "dialog-model": "закончились кредиты",
        "fallback-model": None,
    }

    async def litellm_ok() -> bool:
        return True

    async def models() -> dict[str, str | None]:
        return dict(problems)

    bot = FakeSender()
    svc = MonitorService(
        sessions, SettingsService(sessions, ttl_s=0), cast(Bot, bot), litellm_ok, models
    )
    hour = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)

    assert await svc.check(hour) == ["⚠️ Модель dialog-model: закончились кредиты"]
    assert await svc.check(hour + timedelta(minutes=1)) == []  # не время пробы — без изменений
    problems["dialog-model"] = None
    assert await svc.check(hour + timedelta(minutes=7)) == []  # «в норме» только после пробы
    assert await svc.check(hour + timedelta(minutes=15)) == ["✅ Модель dialog-model: в норме"]
