"""D1-1: ответ менеджера с ключом повтора не дублируется ни при последовательном, ни при
параллельном повторе.

Ключ занимается до отправки (строка `meta.delivery = sending` под advisory-блокировкой):
второй запрос во время отправки — 409 `reply_in_progress`, после — тот же id; отказ Telegram
освобождает ключ; таймаут и «Telegram принял, запись итога упала» оставляют ответ `sending` —
повтор не шлёт второе сообщение, после `STALE_SENDING` получает этот ответ.
"""

import asyncio
from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bus import runtime
from app.bus.runtime import build_bus
from app.domain.errors import ConflictError
from app.models.leads import Message
from app.security.principal import Principal
from app.services import lead_messenger
from app.services.lead_messenger import LeadMessenger, ReplyOnce
from app.services.leads import DeliveryError, LeadService
from app.services.settings import SettingsService
from tests.integration.crm_helpers import escalated_lead, make_user

pytestmark = pytest.mark.integration

KEY = "draft-7001-abcdef"
TEXT = "Цена — в КП сегодня"


@pytest.fixture
def bus(sessions: async_sessionmaker[AsyncSession]) -> Iterator[Any]:
    stand = build_bus(sessions, None)
    runtime.set_bus(stand)
    yield stand
    runtime.set_bus(None)


class GatedSender:
    """Telegram, который отвечает, когда тест разрешит; `fail` — отказ, `hang` — молчание."""

    def __init__(self) -> None:
        self.calls = 0
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.fail = False
        self.hang = False

    async def send_message(self, chat_id: int, text: str, **_: Any) -> Any:
        self.calls += 1
        self.started.set()
        if self.hang:
            await asyncio.sleep(3600)
        await self.release.wait()
        if self.fail:
            raise RuntimeError("telegram refused")
        return type("Sent", (), {"message_id": 500 + self.calls})()


async def setup(
    sessions: async_sessionmaker[AsyncSession], sender: GatedSender, tg: int
) -> tuple[LeadService, Principal, int]:
    lead_id = await escalated_lead(sessions, tg_user_id=tg)
    account, _ = await make_user(sessions, f"d1-once-{tg}@railtech.uz", ["manager"])
    who = Principal(user_id=account.id, full_name="Менеджер", roles=("manager",))
    service = LeadService(sessions, SettingsService(sessions), LeadMessenger(sessions, sender))
    gate, fail, hang = sender.release.is_set(), sender.fail, sender.hang
    # «Забрать» само пишет лиду («менеджер подключился») — этот ответ проходит без задержек
    sender.release.set()
    sender.fail = sender.hang = False
    await service.take(who, lead_id)
    sender.calls = 0
    sender.started.clear()
    if not gate:
        sender.release.clear()
    sender.fail, sender.hang = fail, hang
    return service, who, lead_id


async def keyed_rows(sessions: async_sessionmaker[AsyncSession]) -> list[Message]:
    """Ответы менеджера с ключом повтора (без сообщения «менеджер подключился» от «Забрать»)."""
    async with sessions() as session:
        rows = await session.scalars(
            select(Message).where(
                Message.role == "manager", Message.meta["client_message_id"].astext == KEY
            )
        )
        return list(rows)


async def events(sessions: async_sessionmaker[AsyncSession]) -> int:
    async with sessions() as session:
        value = await session.scalar(
            text(
                "SELECT count(*) FROM rt_bus_outbox "
                "WHERE type = 'uz.railtech.crm.lead.message_added.v1'"
            )
        )
    return int(value or 0)


async def test_a_parallel_retry_with_the_same_key_does_not_send_twice(
    sessions: async_sessionmaker[AsyncSession], bus: Any
) -> None:
    sender = GatedSender()
    service, who, lead_id = await setup(sessions, sender, 7001)
    baseline = await events(sessions)

    first = asyncio.create_task(service.reply(who, lead_id, TEXT, client_message_id=KEY))
    await asyncio.wait_for(sender.started.wait(), 5)

    with pytest.raises(ConflictError) as busy:
        await service.reply(who, lead_id, TEXT, client_message_id=KEY)
    assert busy.value.details["reason"] == "reply_in_progress"
    assert await events(sessions) == baseline  # событие — только после ответа Telegram

    sender.release.set()
    message_id = await first
    again = await service.reply(who, lead_id, TEXT, client_message_id=KEY)

    assert again == message_id
    assert sender.calls == 1
    (row,) = await keyed_rows(sessions)
    assert row.meta["delivery"] == "sent"
    assert row.tg_message_id is not None
    assert await events(sessions) == baseline + 1


async def test_two_simultaneous_requests_send_one_message(
    sessions: async_sessionmaker[AsyncSession], bus: Any
) -> None:
    sender = GatedSender()
    sender.release.set()
    service, who, lead_id = await setup(sessions, sender, 7002)

    results = await asyncio.gather(
        service.reply(who, lead_id, TEXT, client_message_id=KEY),
        service.reply(who, lead_id, TEXT, client_message_id=KEY),
        return_exceptions=True,
    )

    ids = {r for r in results if isinstance(r, int)}
    busy = [r for r in results if isinstance(r, ConflictError)]
    assert len(ids) == 1
    assert len(ids) + len(busy) == 2
    assert sender.calls == 1
    assert len(await keyed_rows(sessions)) == 1


async def test_a_telegram_refusal_frees_the_key_and_the_retry_sends_once(
    sessions: async_sessionmaker[AsyncSession], bus: Any
) -> None:
    sender = GatedSender()
    sender.release.set()
    sender.fail = True
    service, who, lead_id = await setup(sessions, sender, 7003)

    with pytest.raises(DeliveryError):
        await service.reply(who, lead_id, TEXT, client_message_id=KEY)
    assert await keyed_rows(sessions) == []

    sender.fail = False
    message_id = await service.reply(who, lead_id, TEXT, client_message_id=KEY)
    (row,) = await keyed_rows(sessions)
    assert row.id == message_id
    assert sender.calls == 2


async def test_an_unknown_outcome_never_sends_a_second_copy(
    sessions: async_sessionmaker[AsyncSession], bus: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Таймаут Telegram (мог принять) — ответ остаётся `sending`: повтор — 409, после срока —
    тот же id."""
    sender = GatedSender()
    sender.hang = True
    monkeypatch.setattr(lead_messenger, "REPLY_TIMEOUT_S", 0.2)
    service, who, lead_id = await setup(sessions, sender, 7004)

    with pytest.raises(DeliveryError):
        await service.reply(who, lead_id, TEXT, client_message_id=KEY)
    with pytest.raises(ConflictError):
        await service.reply(who, lead_id, TEXT, client_message_id=KEY)
    monkeypatch.setattr(lead_messenger, "STALE_SENDING", timedelta(0))
    (row,) = await keyed_rows(sessions)
    assert await service.reply(who, lead_id, TEXT, client_message_id=KEY) == row.id
    assert sender.calls == 1


async def test_telegram_accepted_but_the_write_failed_keeps_one_message(
    sessions: async_sessionmaker[AsyncSession], bus: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    sender = GatedSender()
    sender.release.set()
    service, who, lead_id = await setup(sessions, sender, 7005)

    async def broken(self: ReplyOnce, message_id: int, tg_message_id: int | None) -> None:
        raise RuntimeError("db is down")

    monkeypatch.setattr(ReplyOnce, "_confirm", broken)
    message_id = await service.reply(who, lead_id, TEXT, client_message_id=KEY)
    with pytest.raises(ConflictError):
        await service.reply(who, lead_id, TEXT, client_message_id=KEY)
    (row,) = await keyed_rows(sessions)
    assert (row.id, row.meta["delivery"]) == (message_id, "sending")
    assert sender.calls == 1
