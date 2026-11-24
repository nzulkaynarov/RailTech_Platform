"""CH-1: поле ответа по каналу. Канал ответа решает CRM (`reply_via` карточки и очереди), ответ
уходит туда же: письмо с почты компании для лида с адресом, 409 `no_reply_channel` для лида без
канала (а не 502 «Telegram не ответил»), «Вернуть боту» — только лиду с чатом Telegram."""

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.integrations.smtp import SmtpCheck, SmtpConnection
from app.main import create_app
from app.models.email import EmailLog
from app.models.leads import Conversation, Lead, Message
from app.security.secrets_store import SecretCipher
from app.services.mail import MailService
from tests.integration.crm_helpers import escalated_lead, login, make_user
from tests.integration.test_lead_intake import web_body

pytestmark = pytest.mark.integration

SECRETS_KEY = "k" * 64


class FakeTransport:
    async def check(self, connection: SmtpConnection) -> SmtpCheck:
        return SmtpCheck("relay.test", False, 1)

    async def send(self, connection: SmtpConnection, to: str, subject: str, body: str) -> None:
        return None


@pytest.fixture
def client(live_settings: Settings) -> Iterator[TestClient]:
    settings = live_settings.model_copy(update={"secrets_key": SecretStr(SECRETS_KEY)})
    with TestClient(create_app(settings)) as test_client:
        container = test_client.app.state.container  # type: ignore[attr-defined]

        async def enqueue(email_log_id: int) -> int:
            return email_log_id

        container.__dict__["mail_service"] = MailService(
            container.session_factory,
            container.secrets_store,
            SecretCipher(SECRETS_KEY),
            settings,
            container.settings_service,
            FakeTransport(),
            enqueue,
        )
        container.__dict__.pop("lead_service", None)
        yield test_client


async def connect_smtp(sessions: async_sessionmaker[AsyncSession], client: TestClient) -> None:
    admin, password = await make_user(sessions, "ch1-smtp@railtech.uz", ["admin"])
    response = client.put(
        "/api/v1/integrations/smtp",
        json={
            "host": "smtp.test",
            "port": 587,
            "security": "starttls",
            "from_email": "crm@railtech.test",
            "from_name": "RailTech",
            "username": "crm",
            "smtp_password": "relay-password-Ab12-test",
            "password": password,
        },
        headers=login(client, admin.email, password),
    )
    assert response.status_code == 200, response.text


async def taken_web_lead(
    sessions: async_sessionmaker[AsyncSession],
    client: TestClient,
    live_settings: Settings,
    name: str,
    **patch: Any,
) -> tuple[int, dict[str, str]]:
    response = client.post("/api/v1/leads/web", json=web_body(live_settings, **patch))
    assert response.status_code == 202, response.text
    lead_id = int(response.json()["lead_id"])
    manager, password = await make_user(sessions, f"{name}@railtech.uz", ["manager"])
    me = login(client, manager.email, password)
    assert client.post(f"/api/v1/leads/{lead_id}/actions/take", headers=me).status_code == 200
    return lead_id, me


async def count(sessions: async_sessionmaker[AsyncSession], model: Any) -> int:
    async with sessions() as session:
        return int(await session.scalar(select(func.count()).select_from(model)) or 0)


async def test_web_lead_with_phone_only_gets_a_refusal_not_a_telegram_error(
    client: TestClient, sessions: async_sessionmaker[AsyncSession], live_settings: Settings
) -> None:
    lead_id, me = await taken_web_lead(sessions, client, live_settings, "ch1-phone", email=None)

    card = client.get(f"/api/v1/leads/{lead_id}", headers=me).json()
    sent = client.post(
        f"/api/v1/leads/{lead_id}/messages", json={"text": "Здравствуйте"}, headers=me
    )

    assert (card["reply_via"], card["reply_blocked"]) == (None, "phone_only")
    assert card["can_return_to_bot"] is False
    assert sent.status_code == 409
    assert sent.json()["details"] == {"reason": "no_reply_channel", "blocked": "phone_only"}
    assert await count(sessions, Message) == 0


async def test_web_lead_with_email_is_answered_by_one_letter_and_a_repeat_sends_no_second(
    client: TestClient, sessions: async_sessionmaker[AsyncSession], live_settings: Settings
) -> None:
    await connect_smtp(sessions, client)
    lead_id, me = await taken_web_lead(sessions, client, live_settings, "ch1-mail")
    assert client.get(f"/api/v1/leads/{lead_id}", headers=me).json()["reply_via"] == "email"
    letters_before = await count(sessions, EmailLog)
    body = {"text": "Добрый день, КП пришлём сегодня", "client_message_id": "mail-key-1"}

    first = client.post(f"/api/v1/leads/{lead_id}/messages", json=body, headers=me)
    again = client.post(f"/api/v1/leads/{lead_id}/messages", json=body, headers=me)

    assert first.status_code == again.status_code == 200, first.text
    assert first.json()["id"] == again.json()["id"]
    async with sessions() as session:
        letters = (await session.scalars(select(EmailLog).where(EmailLog.ref_kind == "lead"))).all()
        message = await session.get(Message, first.json()["id"])
        assert message is not None
        conversation = await session.get(Conversation, message.conversation_id)
        lead = await session.get(Lead, lead_id)
    assert len(letters) == 1
    assert await count(sessions, EmailLog) == letters_before + 1
    assert (letters[0].to_email, letters[0].ref_id, letters[0].status) == (
        "a@rail.uz",
        str(lead_id),
        "queued",
    )
    assert f"L-{lead_id:04d}" in letters[0].subject
    assert conversation is not None
    assert conversation.channel == "email"
    assert message.meta["channel"] == "email"
    assert message.meta["email_log_id"] == letters[0].id
    assert lead is not None
    assert lead.last_human_msg_at is not None


async def test_without_the_mail_connector_the_reply_is_refused_and_nothing_is_recorded(
    client: TestClient, sessions: async_sessionmaker[AsyncSession], live_settings: Settings
) -> None:
    lead_id, me = await taken_web_lead(sessions, client, live_settings, "ch1-nosmtp")

    sent = client.post(
        f"/api/v1/leads/{lead_id}/messages", json={"text": "Здравствуйте"}, headers=me
    )

    assert sent.status_code == 409
    assert sent.json()["details"]["reason"] == "smtp_not_configured"
    assert await count(sessions, Message) == 0


async def test_return_to_bot_is_refused_for_a_lead_without_telegram(
    client: TestClient, sessions: async_sessionmaker[AsyncSession], live_settings: Settings
) -> None:
    lead_id, me = await taken_web_lead(sessions, client, live_settings, "ch1-bot")

    refused = client.post(f"/api/v1/leads/{lead_id}/actions/return_to_bot", json={}, headers=me)

    assert refused.status_code == 409
    assert refused.json()["details"]["reason"] == "no_bot_channel"
    async with sessions() as session:
        lead = await session.get(Lead, lead_id)
    assert lead is not None
    assert lead.owner_mode == "human"


async def test_inbox_tells_where_the_reply_goes(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    lead_id = await escalated_lead(sessions, tg_user_id=6301)
    manager, password = await make_user(sessions, "ch1-inbox@railtech.uz", ["manager"])
    me = login(client, manager.email, password)

    inbox = client.get("/api/v1/inbox", headers=me).json()

    [item] = [i for i in inbox["escalations"] if i["id"] == lead_id]
    assert (item["reply_via"], item["reply_blocked"], item["can_return_to_bot"]) == (
        "telegram",
        None,
        True,
    )
