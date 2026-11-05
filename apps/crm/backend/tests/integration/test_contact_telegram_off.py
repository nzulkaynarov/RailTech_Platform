"""Telegram, отключённый контактом в кабинете (`notifications_off_at`, NOTIFY-1): каждый путь
клиентской рассылки его не берёт, явное подтверждение менеджером включает снова."""

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bus import notice_mail, runtime
from app.bus.runtime import build_bus
from app.config import Settings
from app.models.clients import Client, ClientContact
from app.models.leads import Lead, TelegramIdentity
from app.models.notices import ClientNotice
from app.repositories import leads as repo
from app.schemas.client_requests import RequestContactIn
from app.security.principal import Principal
from app.services.client_notices import WEB_CONFIRMATION, ClientNoticeService
from app.services.clients import ClientService
from app.services.contact_telegram import ContactTelegramService
from app.services.erp_acceptance_code import contact_telegram
from app.services.erp_handoff import _contacts_payload
from app.services.portal_invites import telegram_of_contact
from app.services.request_contacts import request_contact
from app.services.settings import SettingsService
from tests.integration.crm_helpers import make_user
from tests.integration.test_contact_telegram import (
    USER,
    FakeBot,
    chat,
    contact,
    unlink_event,
)
from tests.unit.test_contact_link import BEFORE, PAIR_SECRET, token

pytestmark = pytest.mark.integration


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


async def switched_off(
    sessions: async_sessionmaker[AsyncSession], service: ContactTelegramService
) -> tuple[int, int, int]:
    """Основной контакт подключил Telegram и отключил его: (client_id, contact_id, lead_id)."""
    lead_id = await chat(sessions, USER)
    client_id, contact_id = await contact(sessions)
    async with sessions() as session, session.begin():
        row = await session.get(ClientContact, contact_id)
        assert row is not None
        row.is_primary = True
    await service.bind(USER, token(contact=contact_id), BEFORE)
    async with sessions() as session, session.begin():
        await service.unlink_requested(session, unlink_event(client_id, contact_id))
    return client_id, contact_id, lead_id


async def rebound_by_make_customer(
    sessions: async_sessionmaker[AsyncSession], client_id: int
) -> None:
    """Как `_bind_identities` («Сделать клиентом», заявка): Telegram лида снова у клиента, отметка
    отключения сохраняется."""
    async with sessions() as session, session.begin():
        found = await repo.get_identity(session, USER)
        assert found is not None
        found.client_id, found.verified_at = client_id, datetime.now(UTC)


async def test_manager_confirmation_switches_mailings_back_on(
    sessions: async_sessionmaker[AsyncSession], service: ContactTelegramService
) -> None:
    client_id, _, _ = await switched_off(sessions, service)
    manager, _ = await make_user(sessions, "manager@alfa.example", ["manager"])

    await ClientService(sessions).link_identity(
        Principal(manager.id, "Менеджер", ("manager",)), client_id, USER
    )

    async with sessions() as session:
        assert await notice_mail.client_chats(session, client_id, with_leads=True) == [USER]


async def test_implicit_rebinding_keeps_mailings_off(
    sessions: async_sessionmaker[AsyncSession], service: ContactTelegramService
) -> None:
    client_id, _, _ = await switched_off(sessions, service)
    await rebound_by_make_customer(sessions, client_id)

    async with sessions() as session:
        assert await notice_mail.client_chats(session, client_id, with_leads=False) == []


async def test_invitation_and_acceptance_code_do_not_fall_back_to_a_switched_off_telegram(
    sessions: async_sessionmaker[AsyncSession], service: ContactTelegramService
) -> None:
    client_id, contact_id, _ = await switched_off(sessions, service)
    await rebound_by_make_customer(sessions, client_id)

    async with sessions() as session:
        client = await session.get(Client, client_id)
        row = await session.get(ClientContact, contact_id)
        assert client is not None
        assert row is not None
        assert await telegram_of_contact(session, client, row) is None
        assert await contact_telegram(session, client, row) is None


async def test_new_request_contact_does_not_take_a_switched_off_lead_telegram(
    sessions: async_sessionmaker[AsyncSession], service: ContactTelegramService
) -> None:
    client_id, _, lead_id = await switched_off(sessions, service)
    manager, _ = await make_user(sessions, "manager@alfa.example", ["manager"])

    async with sessions() as session, session.begin():
        client = await session.get(Client, client_id)
        lead = await session.get(Lead, lead_id)
        assert client is not None
        new = await request_contact(
            session,
            client,
            lead,
            RequestContactIn(
                full_name="Второй", email="second@alfa.example", use_lead_telegram=True
            ),
            Principal(manager.id, "Менеджер", ("manager",)),
        )
        assert new.telegram_identity_id is None


async def test_web_confirmation_does_not_use_a_switched_off_telegram(
    sessions: async_sessionmaker[AsyncSession],
    service: ContactTelegramService,
    live_settings: Settings,
) -> None:
    _, _, lead_id = await switched_off(sessions, service)
    bot = FakeBot()

    async def provider() -> Any:
        return bot

    async def username() -> str:
        return "example_bot"

    notices = ClientNoticeService(
        sessions,
        SettingsService(sessions, ttl_s=0),
        None,  # type: ignore[arg-type]  # почта не нужна: у лида нет адреса
        provider,
        username,
        b"start-link-key",
        live_settings,
    )
    async with sessions() as session, session.begin():
        lead = await session.get(Lead, lead_id)
        assert lead is not None
        planned = await notices.plan_web_confirmation(session, lead)
        assert planned is not None
        assert planned.channel != "telegram"
        queued = ClientNotice(
            kind=WEB_CONFIRMATION,
            lead_id=lead_id,
            channel="telegram",
            status="queued",
            dedupe_key="test:off",
        )
        session.add(queued)
        await session.flush()
        queued_id = queued.id

    assert await notices.deliver(queued_id) == "failed"
    assert bot.sent == []


async def test_identity_row_keeps_the_mark_until_linked_again(
    sessions: async_sessionmaker[AsyncSession], service: ContactTelegramService
) -> None:
    _, contact_id, _ = await switched_off(sessions, service)
    async with sessions() as session:
        found = await repo.get_identity(session, USER)
        assert found is not None
        assert found.notifications_off_at is not None

    await service.bind(USER, token(contact=contact_id, nonce=b"\x04" * 9), BEFORE)

    async with sessions() as session:
        again = await session.get(TelegramIdentity, found.id)
        assert again is not None
        assert again.notifications_off_at is None


async def test_handoff_to_erp_does_not_give_the_primary_contact_a_switched_off_lead_telegram(
    sessions: async_sessionmaker[AsyncSession], service: ContactTelegramService
) -> None:
    client_id, _, lead_id = await switched_off(sessions, service)
    async with sessions() as session, session.begin():
        client = await session.get(Client, client_id)
        lead = await session.get(Lead, lead_id)
        assert client is not None
        assert lead is not None
        identities = list(
            await session.scalars(
                select(TelegramIdentity).where(TelegramIdentity.lead_id == lead_id)
            )
        )
        payload = await _contacts_payload(session, client, lead, identities)

    assert [c.telegram_user_id for c in payload if c.is_primary] == [None]
