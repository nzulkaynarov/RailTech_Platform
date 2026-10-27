"""«Заявка принята, считаем» по событию ERP `request.created` (D1-9, SPEC-v3 §3.1 шаг 2, §8).

Бот, а клиенту без Telegram — письмо; повторная доставка того же события второго сообщения не
даёт (inbox шины и ключи в `erp_event_notices`); заявка сотрудника в ERP клиенту не объявляется;
итог — в `client_notices`.
"""

import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.errors import ConflictError, Reason
from app.models.clients import ClientContact
from app.models.integrations import ErpEventNotice
from app.models.leads import TelegramIdentity
from app.models.notices import ClientNotice
from app.services.mail_templates import RenderedEmail
from app.services.settings import SettingsService
from tests.bus_events import envelope_for
from tests.integration.bus_harness import ERP_DEAL, T0, Harness, data_for, event_type_of

pytestmark = pytest.mark.integration

CABINET = "https://cabinet.example.com"


class FakeMail:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, RenderedEmail]] = []
        self.error: Exception | None = None

    async def send_rendered(self, template: str, to: str, rendered: RenderedEmail, **_: Any) -> Any:
        if self.error is not None:
            raise self.error
        self.sent.append((template, to, rendered))
        return type("Log", (), {"id": len(self.sent)})()


@pytest.fixture
def harness(sessions: async_sessionmaker[AsyncSession]) -> Iterator[Harness]:
    stand = Harness(sessions)
    yield stand
    stand.close()


@pytest.fixture
def mail(harness: Harness) -> FakeMail:
    fake = FakeMail()
    harness.notices._mail = fake  # type: ignore[assignment]
    return fake


async def set_cabinet(sessions: async_sessionmaker[AsyncSession]) -> None:
    await SettingsService(sessions, ttl_s=0).update(
        "company",
        {"name": "RailTech", "crm_base_url": "http://x", "cabinet_url": CABINET},
        None,
        None,
    )


async def add_email(sessions: async_sessionmaker[AsyncSession], client_id: int, email: str) -> None:
    async with sessions() as session, session.begin():
        session.add(
            ClientContact(client_id=client_id, full_name="Порядок", email=email, is_primary=True)
        )


async def notice_rows(sessions: async_sessionmaker[AsyncSession]) -> list[ClientNotice]:
    async with sessions() as session:
        return list((await session.scalars(select(ClientNotice).order_by(ClientNotice.id))).all())


async def test_client_in_telegram_gets_the_message_with_the_open_cabinet_button(
    harness: Harness, mail: FakeMail, sessions: async_sessionmaker[AsyncSession]
) -> None:
    await set_cabinet(sessions)
    client_id, _ = await harness.seed_client()
    event_id = await harness.store("request.created", client_id)

    assert await harness.process(event_id) == "processed"

    [(chat, text)] = harness.bot.sent
    assert chat == 777
    assert text.startswith(f"Заявка D-{ERP_DEAL} принята, считаем")
    button = harness.bot.markups[0].inline_keyboard[0][0]
    assert (button.text, button.url) == ("Открыть кабинет", CABINET)
    assert mail.sent == [], "бот ушёл — письмо не нужно"
    [row] = await notice_rows(sessions)
    assert (row.kind, row.client_id, row.channel, row.status) == (
        "request_accepted",
        client_id,
        "telegram",
        "sent",
    )


async def test_redelivery_of_the_same_event_does_not_duplicate_the_message(
    harness: Harness, mail: FakeMail, sessions: async_sessionmaker[AsyncSession]
) -> None:
    await set_cabinet(sessions)
    client_id, _ = await harness.seed_client()
    envelope_id = await harness.store("request.created", client_id, event_id=str(uuid.uuid4()))
    assert await harness.process(envelope_id) == "processed"

    # ERP не получила ответ и шлёт то же событие снова; сборщик тоже пробует досыпать.
    envelope = envelope_for(
        event_type_of("request.created"),
        data_for("request.created", client_id),
        time=T0,
        event_id=envelope_id,
    )
    repeat = await harness.post(envelope)
    assert repeat.body["status"] == "duplicate"
    assert await harness.notices.deliver(envelope_id) == 0

    assert len(harness.bot.sent) == 1
    assert len(await notice_rows(sessions)) == 1


async def test_client_without_telegram_gets_a_letter_once(
    harness: Harness, mail: FakeMail, sessions: async_sessionmaker[AsyncSession]
) -> None:
    await set_cabinet(sessions)
    client_id, _ = await harness.seed_client(tg_user_id=None)
    await add_email(sessions, client_id, "ivan@client.uz")
    event_id = await harness.store("request.created", client_id)

    assert await harness.process(event_id) == "processed"
    assert await harness.notices.deliver(event_id) == 0

    [(template, to, rendered)] = mail.sent
    assert (template, to) == ("request_accepted", "ivan@client.uz")
    assert rendered.subject == f"Заявка D-{ERP_DEAL} принята"
    assert CABINET in rendered.body
    assert f"D-{ERP_DEAL}" in rendered.body
    assert harness.bot.sent == []
    [row] = await notice_rows(sessions)
    assert (row.channel, row.status) == ("email", "queued")


async def test_telegram_of_the_clients_lead_counts_even_if_not_linked_to_the_client(
    harness: Harness, mail: FakeMail, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """Лид только с Telegram: аккаунт привязан к лиду клиента, к клиенту — ещё нет (D1-2 свяжет)."""
    await set_cabinet(sessions)
    client_id, _ = await harness.seed_client()
    async with sessions() as session, session.begin():
        await session.execute(update(TelegramIdentity).values(client_id=None))
    event_id = await harness.store("request.created", client_id)

    assert await harness.process(event_id) == "processed"

    assert [chat for chat, _ in harness.bot.sent] == [777]
    assert mail.sent == []


async def test_no_channel_at_all_is_quiet_and_not_retried(
    harness: Harness, mail: FakeMail, sessions: async_sessionmaker[AsyncSession]
) -> None:
    client_id, _ = await harness.seed_client(tg_user_id=None)
    event_id = await harness.store("request.created", client_id)

    assert await harness.process(event_id) == "processed"

    assert harness.bot.sent == []
    assert mail.sent == []
    notice = await harness.notice(event_id)
    assert notice is not None
    assert notice.notified_at is not None


async def test_staff_request_in_erp_is_not_announced_to_the_client(
    harness: Harness, mail: FakeMail
) -> None:
    client_id, _ = await harness.seed_client()
    event_id = await harness.store(
        "request.created", client_id, payload={"source": "erp", "erp_request_id": ERP_DEAL}
    )

    assert await harness.process(event_id) == "processed"

    assert harness.bot.sent == []
    assert mail.sent == []


async def test_request_from_the_cabinet_is_confirmed_too(harness: Harness, mail: FakeMail) -> None:
    client_id, _ = await harness.seed_client()
    event_id = await harness.store(
        "request.created", client_id, payload={"source": "cabinet", "erp_request_id": ERP_DEAL}
    )
    assert await harness.process(event_id) == "processed"
    assert len(harness.bot.sent) == 1


async def test_mail_not_configured_is_recorded_and_not_retried_forever(
    harness: Harness, mail: FakeMail, sessions: async_sessionmaker[AsyncSession]
) -> None:
    client_id, _ = await harness.seed_client(tg_user_id=None)
    await add_email(sessions, client_id, "ivan@client.uz")
    mail.error = ConflictError("no smtp", reason=Reason.SMTP_NOT_CONFIGURED)
    event_id = await harness.store("request.created", client_id)

    assert await harness.process(event_id) == "processed"

    [row] = await notice_rows(sessions)
    assert (row.channel, row.status, row.error) == ("email", "skipped", "smtp_not_configured")
    notice = await harness.notice(event_id)
    assert notice is not None
    assert notice.notified_at is not None


async def test_unexpected_mail_failure_is_retried_by_the_sweeper(
    harness: Harness, mail: FakeMail, sessions: async_sessionmaker[AsyncSession]
) -> None:
    client_id, _ = await harness.seed_client(tg_user_id=None)
    await add_email(sessions, client_id, "ivan@client.uz")
    mail.error = RuntimeError("queue is down")
    event_id = await harness.store("request.created", client_id)

    assert await harness.process(event_id) == "processed"
    pending = await harness.notice(event_id)
    assert pending is not None
    assert pending.notified_at is None, "письмо ещё не ушло — ждёт повтора"

    mail.error = None
    assert await harness.notices.deliver(event_id) == 1
    assert await harness.notices.deliver(event_id) == 0
    assert len(mail.sent) == 1


async def test_notice_items_carry_the_texts_in_the_leads_language(
    harness: Harness, sessions: async_sessionmaker[AsyncSession]
) -> None:
    client_id, lead_id = await harness.seed_client()
    async with sessions() as session, session.begin():
        from app.models.leads import Lead

        await session.execute(update(Lead).where(Lead.id == lead_id).values(language="uz"))
    event_id = await harness.store("request.created", client_id)
    await harness.process(event_id)

    [(_, text)] = harness.bot.sent
    assert text.startswith("Ariza D-9001 qabul qilindi")
    stored: ErpEventNotice | None = await harness.notice(event_id)
    assert stored is not None
    assert stored.items[0]["email"]["lang"] == "uz"
