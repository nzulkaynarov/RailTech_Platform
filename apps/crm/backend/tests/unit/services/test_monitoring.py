"""Монитор переживает недоступный Telegram: состояние сохраняется, отправка — после коммита."""

import contextlib
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
from aiogram import Bot
from aiogram.exceptions import TelegramNetworkError
from aiogram.methods import SendMessage
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.alerts import Check, Decision
from app.domain.staff_notify import Staff
from app.models.system import SystemAlert
from app.repositories import monitoring as repo
from app.services import staff_notifier
from app.services.monitoring import MonitorService, alert_text, report_text
from app.services.settings import SettingsService

NOW = datetime(2026, 10, 12, 9, 0, tzinfo=UTC)
CHANNEL = -100500


class Store:
    def __init__(self) -> None:
        self.rows: dict[str, SystemAlert] = {}
        self.queue = 0


class FakeSession:
    def __init__(self, store: Store) -> None:
        self.store = store

    def add(self, row: SystemAlert) -> None:
        self.store.rows[row.key] = row

    @contextlib.asynccontextmanager
    async def begin(self) -> AsyncIterator[None]:
        yield

    async def scalars(self, _: object) -> list[SystemAlert]:
        return list(self.store.rows.values())


class FlakyBot:
    def __init__(self) -> None:
        self.down = True
        self.sent: list[tuple[int, str]] = []

    async def send_message(self, chat_id: int, text: str, **kwargs: Any) -> Any:
        assert kwargs.get("request_timeout") == staff_notifier.SEND_TIMEOUT_S
        if self.down:
            raise TelegramNetworkError(SendMessage(chat_id=chat_id, text=text), "timeout")
        self.sent.append((chat_id, text))
        return object()


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> Store:
    data = Store()

    async def alert_states(_: object) -> dict[str, SystemAlert]:
        return dict(data.rows)

    async def zero(*_: object) -> int:
        return 0

    async def queue(*_: object) -> int:
        return data.queue

    async def nothing(*_: object) -> dict[str, int]:
        return {}

    async def spent(*_: object) -> float:
        return 0.0

    async def recovered(*_: object) -> frozenset[str]:
        return frozenset()

    async def staff(*_: object, **__: object) -> list[Staff]:
        return []

    monkeypatch.setattr(repo, "alert_states", alert_states)
    monkeypatch.setattr(repo, "queue_size", queue)
    monkeypatch.setattr(repo, "failed_tasks", nothing)
    monkeypatch.setattr(repo, "spent_since", spent)
    monkeypatch.setattr(repo, "recovered_tasks", recovered)
    monkeypatch.setattr(staff_notifier, "_staff", staff)
    return data


def service(store: Store, bot: FlakyBot, litellm: list[bool], models: Any = None) -> MonitorService:
    @contextlib.asynccontextmanager
    async def sessions() -> AsyncIterator[FakeSession]:
        yield FakeSession(store)

    async def probe() -> bool:
        return litellm[0]

    factory = cast(async_sessionmaker[AsyncSession], sessions)
    settings = SettingsService(factory)

    async def get() -> Any:
        from app.schemas.settings import AppSettings

        cfg = AppSettings()
        return cfg.model_copy(
            update={"notifications": cfg.notifications.model_copy(update={"channel_id": CHANNEL})}
        )

    settings.get = get  # type: ignore[method-assign]
    return MonitorService(factory, settings, cast(Bot, bot), probe, models)


async def test_telegram_down_keeps_state_and_retries_next_run(store: Store) -> None:
    bot = FlakyBot()
    svc = service(store, bot, [True])
    store.queue = 150
    assert await svc.check(NOW) == []  # Telegram лежит — не упали
    row = store.rows["queue_size"]
    assert (row.active, row.sent_at) == (True, None)  # состояние сохранено, не отправлено
    bot.down = False
    sent = await svc.check(NOW + timedelta(minutes=1))
    assert [text.splitlines()[0] for text in sent] == [
        "⚠️ Очередь задач: 150 задач в ожидании (порог 100)"
    ]
    assert row.sent_at == NOW + timedelta(minutes=1)
    store.queue = 0
    assert await svc.check(NOW + timedelta(minutes=2)) == ["✅ Очередь задач: в норме"]
    assert row.active is False


async def test_gateway_down_is_not_a_monitor_alert_and_old_rows_close_quietly(
    store: Store,
) -> None:
    """Второго отправителя «Сбоя сразу» нет: шлюз — строка центра сервисов (15 минут подряд)."""
    bot = FlakyBot()
    bot.down = False
    svc = service(store, bot, [False])
    for minutes in (0, 2, 5, 30):
        assert await svc.check(NOW + timedelta(minutes=minutes)) == []
    assert "litellm_down" not in store.rows
    assert bot.sent == []
    # живая строка прежнего алерта (с прошлого релиза) закрывается молча, без «в норме»
    store.rows["litellm_down"] = SystemAlert(
        key="litellm_down", active=True, detail="x", first_seen_at=NOW, sent_at=NOW, updated_at=NOW
    )
    store.rows["ai_failures"] = SystemAlert(
        key="ai_failures", active=True, detail="x", first_seen_at=NOW, sent_at=NOW, updated_at=NOW
    )
    assert await svc.check(NOW + timedelta(minutes=31)) == []
    assert (store.rows["litellm_down"].active, store.rows["ai_failures"].active) == (False, False)
    assert bot.sent == []


async def test_healthy_model_gets_row_with_probe_time(store: Store) -> None:
    async def models() -> dict[str, str | None]:
        return {"dialog-model": None}

    bot = FlakyBot()
    bot.down = False
    svc = service(store, bot, [True], models)
    assert await svc.check(NOW) == []
    row = store.rows["model:dialog-model"]
    assert (row.active, row.updated_at) == (False, NOW)
    await svc.check(NOW + timedelta(hours=1))
    assert row.updated_at == NOW + timedelta(hours=1)


def test_alert_text_has_hint_and_escapes() -> None:
    item = Check("failed_task:x", True, "Задача «x»", "a < b", hint="сделать")
    assert alert_text(item, Decision.FIRE) == "⚠️ Задача «x»: a &lt; b\nЧто делать: сделать"
    assert alert_text(item, Decision.RESOLVE) == "✅ Задача «x»: в норме"


def test_report_without_cost_with_figures() -> None:
    figures = repo.DailyFigures(
        leads=3,
        escalations=2,
        open_escalations=1,
        open_gaps=4,
        cost_usd=1.5,
        sla_overdue=1,
        take_median_s=12 * 60,
        taken_by=(("Анна", 2),),
        top_gaps=("цена доставки",),
    )
    text = report_text(figures, "12.10", "https://crm.example.com/dashboard")
    assert "$" not in text
    assert "просрочен срок реакции: 1" in text
    assert "медиана до «Забрать»: 12 мин" in text
    assert "Анна — 2" in text
    assert "«цена доставки»" in text
    assert '<a href="https://crm.example.com/dashboard">' in text
