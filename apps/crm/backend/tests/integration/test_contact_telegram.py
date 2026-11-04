"""Привязка Telegram контактом по ссылке из кабинета и отключение по запросу ERP (NOTIFY-1)."""

import asyncio
import dataclasses
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from rt_bus import Event
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bus import notice_mail, runtime
from app.bus.runtime import build_bus
from app.domain import client_texts
from app.models.auth import AuditLog
from app.models.clients import Client, ClientContact
from app.models.leads import Lead, TelegramIdentity, TelegramLinkNonce
from app.repositories import leads as repo
from app.services.contact_telegram import UNLINK_REQUESTED, ContactTelegramService
from app.services.contact_telegram_test import TEST_REQUESTED, TelegramTestDelivery
from app.services.start_links import StartLinkService
from tests.integration.crm_helpers import make_user
from tests.unit.test_contact_link import BEFORE, PAIR_SECRET, token

pytestmark = pytest.mark.integration

USER, OTHER_USER = 5501, 5502
CONTACT_UPDATED = "uz.railtech.crm.contact.updated.v1"


@pytest.fixture(autouse=True)
def _bus(sessions: async_sessionmaker[AsyncSession]) -> Iterator[None]:
    runtime.set_bus(build_bus(sessions, None))
    yield
    runtime.set_bus(None)


@pytest.fixture
def service(sessions: async_sessionmaker[AsyncSession]) -> ContactTelegramService:
    async def secrets() -> list[str]:
        return [PAIR_SECRET]

    return ContactTelegramService(sessions, secrets)


async def chat(
    sessions: async_sessionmaker[AsyncSession], tg_user_id: int, language: str = "ru"
) -> int:
    """Telegram, который только что нажал /start (бот уже завёл лида и идентичность)."""
    async with sessions() as session, session.begin():
        lead, _, _ = await repo.create_lead_with_identity(
            session,
            tg_user_id=tg_user_id,
            username=None,
            first_name="Азамат",
            chat_id=tg_user_id,
            language=language,
            identity=None,
        )
        return lead.id


async def contact(
    sessions: async_sessionmaker[AsyncSession], name: str = "ООО Альфа"
) -> tuple[int, int]:
    """(client_id, contact_id) — клиент CRM с контактом без Telegram."""
    async with sessions() as session, session.begin():
        client = Client(name=name, erp_company_id=118)
        session.add(client)
        await session.flush()
        row = ClientContact(client_id=client.id, full_name="Азамат Каримов", email="a@alfa.example")
        session.add(row)
        await session.flush()
        return client.id, row.id


async def identity(sessions: async_sessionmaker[AsyncSession], tg_user_id: int) -> TelegramIdentity:
    async with sessions() as session:
        found = await repo.get_identity(session, tg_user_id)
        assert found is not None
        return found


async def contact_row(sessions: async_sessionmaker[AsyncSession], contact_id: int) -> ClientContact:
    async with sessions() as session:
        row = await session.get(ClientContact, contact_id)
        assert row is not None
        return row


async def published(
    sessions: async_sessionmaker[AsyncSession], event_type: str
) -> list[dict[str, Any]]:
    async with sessions() as session:
        rows = await session.execute(
            text("SELECT envelope FROM rt_bus_outbox WHERE type = :type ORDER BY created_at, id"),
            {"type": event_type},
        )
        return [row["data"] for row in rows.scalars().all()]


async def nonces(sessions: async_sessionmaker[AsyncSession]) -> int:
    async with sessions() as session:
        return int(await session.scalar(select(func.count()).select_from(TelegramLinkNonce)) or 0)


# ── привязка ─────────────────────────────────────────────────────────────────────────


async def test_valid_link_binds_telegram_without_a_manager_and_tells_erp(
    sessions: async_sessionmaker[AsyncSession], service: ContactTelegramService
) -> None:
    lead_id = await chat(sessions, USER)
    client_id, contact_id = await contact(sessions)

    texts = await service.bind(USER, token(contact=contact_id, language=1), BEFORE)

    assert texts == [client_texts.contact_link_bound("uz", "ООО Альфа")]
    assert texts[0].startswith("Tayyor"), "приветствие на языке контакта из токена, а не чата"
    bound = await identity(sessions, USER)
    assert (bound.client_id, bound.verified_by_user_id) == (client_id, None)
    assert bound.verified_at is not None
    assert (await contact_row(sessions, contact_id)).telegram_identity_id == bound.id
    async with sessions() as session:
        lead = await session.get(Lead, lead_id)
        assert lead is not None
        assert lead.client_id == client_id
        actions = (await session.scalars(select(AuditLog.action))).all()
    assert "client.contact_telegram_self_link" in actions
    (event,) = await published(sessions, CONTACT_UPDATED)
    assert event["contact"]["crm_contact_id"] == contact_id
    assert event["contact"]["telegram_user_id"] == USER
    assert event["contact"]["telegram_name"] == "Азамат", "кабинет покажет, какой аккаунт привязан"


async def test_bot_start_routes_the_contact_link_to_the_binding(
    sessions: async_sessionmaker[AsyncSession], service: ContactTelegramService
) -> None:
    await chat(sessions, USER)
    _, contact_id = await contact(sessions)
    links = StartLinkService(sessions, b"start-link-key", contacts=service)

    result = await links.apply(USER, token(contact=contact_id, language=2), BEFORE)

    assert result.texts == [client_texts.contact_link_bound("en", "ООО Альфа")]


async def test_reused_link_is_refused_neutrally(
    sessions: async_sessionmaker[AsyncSession], service: ContactTelegramService
) -> None:
    await chat(sessions, USER)
    await chat(sessions, OTHER_USER)
    _, contact_id = await contact(sessions)
    link = token(contact=contact_id)
    await service.bind(USER, link, BEFORE)

    again = await service.bind(OTHER_USER, link, BEFORE)

    assert again == [client_texts.contact_link_refused("ru")]
    assert (await identity(sessions, OTHER_USER)).client_id is None
    assert len(await published(sessions, CONTACT_UPDATED)) == 1


async def test_parallel_reuse_binds_exactly_one_telegram(
    sessions: async_sessionmaker[AsyncSession], service: ContactTelegramService
) -> None:
    """Пересланная ссылка, открытая двумя людьми одновременно: привязка ровно одна (мутационная
    проверка в PR: без погашения nonce оба Telegram — подтверждённые аккаунты клиента)."""
    await chat(sessions, USER)
    await chat(sessions, OTHER_USER)
    client_id, contact_id = await contact(sessions)
    link = token(contact=contact_id)

    results = await asyncio.gather(
        *(service.bind(user, link, BEFORE) for user in (USER, OTHER_USER) * 3)
    )

    assert (
        sum(texts == [client_texts.contact_link_bound("uz", "ООО Альфа")] for texts in results) == 1
    )
    async with sessions() as session:
        verified = (
            await session.scalars(
                select(TelegramIdentity.tg_user_id).where(
                    TelegramIdentity.client_id == client_id,
                    TelegramIdentity.verified_at.is_not(None),
                )
            )
        ).all()
    assert len(verified) == 1
    assert await nonces(sessions) == 1
    assert len(await published(sessions, CONTACT_UPDATED)) == 1


@pytest.mark.parametrize(
    "case",
    ["expired", "forged", "unknown_contact"],
)
async def test_expired_forged_and_unknown_contact_get_the_same_neutral_refusal(
    sessions: async_sessionmaker[AsyncSession], service: ContactTelegramService, case: str
) -> None:
    await chat(sessions, USER, language="en")
    _, contact_id = await contact(sessions)
    link, moment = {
        "expired": (token(contact=contact_id), BEFORE + timedelta(minutes=5)),
        "forged": (token("attacker" + "-guess", contact=contact_id), BEFORE),
        "unknown_contact": (token(contact=contact_id + 1000), BEFORE),
    }[case]

    texts = await service.bind(USER, link, moment)

    assert texts == [client_texts.contact_link_refused("en")], "один отказ на всё, на языке чата"
    assert (await identity(sessions, USER)).client_id is None
    assert await published(sessions, CONTACT_UPDATED) == []


async def test_telegram_of_another_client_is_not_relinked_and_the_link_stays_unused(
    sessions: async_sessionmaker[AsyncSession], service: ContactTelegramService
) -> None:
    await chat(sessions, USER)
    other_client, _ = await contact(sessions, "ООО Бета")
    _, contact_id = await contact(sessions)
    async with sessions() as session, session.begin():
        found = await repo.get_identity(session, USER)
        assert found is not None
        found.client_id, found.verified_at = other_client, datetime.now(UTC)

    texts = await service.bind(USER, token(contact=contact_id), BEFORE)

    assert texts == [client_texts.contact_link_taken("ru")]
    assert (await identity(sessions, USER)).client_id == other_client
    assert (await contact_row(sessions, contact_id)).telegram_identity_id is None
    assert await nonces(sessions) == 0, "отказ откатывает транзакцию: ссылка не погашена"


async def test_telegram_of_a_colleague_contact_is_not_moved_silently(
    sessions: async_sessionmaker[AsyncSession], service: ContactTelegramService
) -> None:
    await chat(sessions, USER)
    client_id, colleague_id = await contact(sessions)
    await service.bind(USER, token(contact=colleague_id), BEFORE)
    async with sessions() as session, session.begin():
        second = ClientContact(client_id=client_id, full_name="Второй контакт")
        session.add(second)
        await session.flush()
        second_id = second.id

    texts = await service.bind(USER, token(contact=second_id, nonce=b"\x01" * 9), BEFORE)

    assert texts == [client_texts.contact_link_taken("ru")]
    assert (await contact_row(sessions, colleague_id)).telegram_identity_id is not None
    assert (await contact_row(sessions, second_id)).telegram_identity_id is None


async def test_relinking_with_another_telegram_releases_the_previous_one(
    sessions: async_sessionmaker[AsyncSession], service: ContactTelegramService
) -> None:
    await chat(sessions, USER)
    await chat(sessions, OTHER_USER)
    client_id, contact_id = await contact(sessions)
    await service.bind(USER, token(contact=contact_id), BEFORE)

    texts = await service.bind(OTHER_USER, token(contact=contact_id, nonce=b"\x02" * 9), BEFORE)

    assert texts == [client_texts.contact_link_bound("uz", "ООО Альфа")]
    previous, current = await identity(sessions, USER), await identity(sessions, OTHER_USER)
    assert (previous.client_id, previous.verified_at) == (None, None), (
        "прежний — не аккаунт клиента"
    )
    assert current.client_id == client_id
    assert (await contact_row(sessions, contact_id)).telegram_identity_id == current.id


async def test_self_link_keeps_the_managers_confirmation(
    sessions: async_sessionmaker[AsyncSession], service: ContactTelegramService
) -> None:
    await chat(sessions, USER)
    client_id, contact_id = await contact(sessions)
    manager, _ = await make_user(sessions, "manager@alfa.example", ["manager"])
    async with sessions() as session, session.begin():
        found = await repo.get_identity(session, USER)
        assert found is not None
        found.client_id, found.verified_at = client_id, datetime.now(UTC)
        found.verified_by_user_id = manager.id

    await service.bind(USER, token(contact=contact_id), BEFORE)

    assert (await identity(sessions, USER)).verified_by_user_id == manager.id


# ── отключение по запросу ERP ────────────────────────────────────────────────────────


def unlink_event(client_id: int, contact_id: int) -> Event:
    return Event(
        id=str(uuid.uuid4()),
        source="rt://erp",
        type=UNLINK_REQUESTED,
        time="2026-11-04T07:20:00Z",
        dataschema="rt://contracts/events/erp/contact.telegram_unlink_requested/v1",
        tenant="railtech",
        correlationid=str(uuid.uuid4()),
        data={
            "erp_company_id": 118,
            "crm_client_id": client_id,
            "actor": {"type": "client"},
            "payload": {"erp_contact_id": 310, "crm_contact_id": contact_id},
            "unknown_field": "читатель терпимый",
        },
    )


async def test_unlink_request_releases_telegram_once_and_publishes_the_snapshot(
    sessions: async_sessionmaker[AsyncSession], service: ContactTelegramService
) -> None:
    lead_id = await chat(sessions, USER)
    client_id, contact_id = await contact(sessions)
    await service.bind(USER, token(contact=contact_id), BEFORE)
    async with sessions() as session, session.begin():
        lead = await session.get(Lead, lead_id)
        assert lead is not None
        lead.stage = "customer"

    for _ in range(2):  # повтор события — без второго эффекта
        async with sessions() as session, session.begin():
            await service.unlink_requested(session, unlink_event(client_id, contact_id))

    assert (await contact_row(sessions, contact_id)).telegram_identity_id is None
    released = await identity(sessions, USER)
    assert (released.client_id, released.verified_at) == (None, None)
    async with sessions() as session:
        lead = await session.get(Lead, lead_id)
        assert lead is not None
        # Отключение уведомлений — не потеря клиента: воронка не меняется.
        assert (lead.client_id, lead.stage) == (client_id, "customer")
    bound, unlinked = await published(sessions, CONTACT_UPDATED)
    assert bound["contact"]["telegram_user_id"] == USER
    assert unlinked["contact"]["telegram_user_id"] is None


async def test_unlink_request_for_a_contact_of_another_client_is_ignored(
    sessions: async_sessionmaker[AsyncSession], service: ContactTelegramService
) -> None:
    await chat(sessions, USER)
    _, contact_id = await contact(sessions)
    other_client, _ = await contact(sessions, "ООО Бета")
    await service.bind(USER, token(contact=contact_id), BEFORE)

    async with sessions() as session, session.begin():
        await service.unlink_requested(session, unlink_event(other_client, contact_id))

    assert (await contact_row(sessions, contact_id)).telegram_identity_id is not None
    assert len(await published(sessions, CONTACT_UPDATED)) == 1


async def test_unlinked_telegram_leaves_every_client_mailing_until_linked_again(
    sessions: async_sessionmaker[AsyncSession], service: ContactTelegramService
) -> None:
    """Лид остаётся клиентом (воронка не меняется), но рассылки «через лида клиента» —
    отслеживание запроса D1-9, «заявка принята» — отключённый Telegram больше не берут."""
    await chat(sessions, USER)
    client_id, contact_id = await contact(sessions)
    await service.bind(USER, token(contact=contact_id), BEFORE)
    async with sessions() as session:
        assert await notice_mail.client_chats(session, client_id, with_leads=True) == [USER]

    async with sessions() as session, session.begin():
        await service.unlink_requested(session, unlink_event(client_id, contact_id))
    async with sessions() as session:
        assert await notice_mail.client_chats(session, client_id, with_leads=True) == []
        assert await notice_mail.client_chats(session, client_id, with_leads=False) == []

    await service.bind(USER, token(contact=contact_id, nonce=b"\x03" * 9), BEFORE)
    async with sessions() as session:
        assert await notice_mail.client_chats(session, client_id, with_leads=True) == [USER]


# ── проверочное сообщение ────────────────────────────────────────────────────────────────────────


class FakeBot:
    def __init__(self, error: Exception | None = None) -> None:
        self.sent: list[tuple[int, str]] = []
        self._error = error

    async def send_message(self, chat_id: int, text: str, **kwargs: Any) -> None:
        if self._error is not None:
            raise self._error
        self.sent.append((chat_id, text))


def check_event(client_id: int, contact_id: int) -> Event:
    event = unlink_event(client_id, contact_id)
    event.data["payload"]["language"] = "uz"
    return dataclasses.replace(event, type=TEST_REQUESTED)


def delivery(sessions: async_sessionmaker[AsyncSession], bot: FakeBot) -> TelegramTestDelivery:
    async def provider() -> Any:
        return bot

    return TelegramTestDelivery(sessions, provider)


async def test_test_message_goes_to_the_contacts_own_telegram_in_its_language(
    sessions: async_sessionmaker[AsyncSession], service: ContactTelegramService
) -> None:
    await chat(sessions, USER)
    client_id, contact_id = await contact(sessions)
    await service.bind(USER, token(contact=contact_id), BEFORE)
    bot = FakeBot()

    assert await delivery(sessions, bot).deliver(check_event(client_id, contact_id)) == "processed"

    assert bot.sent == [(USER, client_texts.contact_link_test("uz", "ООО Альфа"))]


async def test_test_message_is_not_sent_to_an_unlinked_or_foreign_contact(
    sessions: async_sessionmaker[AsyncSession], service: ContactTelegramService
) -> None:
    await chat(sessions, USER)
    client_id, contact_id = await contact(sessions)
    other_client, _ = await contact(sessions, "ООО Бета")
    bot = FakeBot()

    assert await delivery(sessions, bot).deliver(check_event(client_id, contact_id)) == "skipped"
    await service.bind(USER, token(contact=contact_id), BEFORE)
    assert await delivery(sessions, bot).deliver(check_event(other_client, contact_id)) == "skipped"
    assert bot.sent == []


async def test_telegram_failure_of_the_test_message_is_reported_not_raised(
    sessions: async_sessionmaker[AsyncSession], service: ContactTelegramService
) -> None:
    await chat(sessions, USER)
    client_id, contact_id = await contact(sessions)
    await service.bind(USER, token(contact=contact_id), BEFORE)

    result = await delivery(sessions, FakeBot(TimeoutError())).deliver(
        check_event(client_id, contact_id)
    )

    assert result == "failed"
