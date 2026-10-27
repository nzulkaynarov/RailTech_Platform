"""Путь нового клиента, шаги 1–2 (D1-9): подтверждение запроса, сообщение менеджерам, срок ответа.

Запрос с сайта (`POST /leads/web`) → в той же транзакции лид, строка подтверждения
(`client_notices`) и срок первого ответа; после коммита — постановка задач (здесь перехвачена),
отправка подтверждения (Telegram или письмо), личное сообщение менеджерам, напоминание о
просрочке. Итог виден в карточке лида (`GET /leads/{id}`).
"""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from aiogram.exceptions import TelegramForbiddenError, TelegramNetworkError
from aiogram.methods import SendMessage
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.domain.start_link import link_key, verify_lead_link
from app.integrations.smtp import SmtpCheck, SmtpConnection
from app.main import create_app
from app.models.auth import User
from app.models.email import EmailLog
from app.models.leads import Lead, LeadNote, Message
from app.models.notices import ClientNotice
from app.repositories import leads as repo
from app.security.secrets_store import SecretCipher
from app.services import web_lead_sla
from app.services.client_notices import MAX_TELEGRAM_ATTEMPTS, ClientNoticeService
from app.services.lead_intake import LeadIntakeService, WebLeadFollowUp
from app.services.lead_merge import merge_with_lead
from app.services.mail import MailService
from app.services.staff_notifier import StaffNotifier
from tests.integration.crm_helpers import FakeSender, login, make_user
from tests.integration.test_lead_intake import web_body

pytestmark = pytest.mark.integration

SECRETS_KEY = "k" * 64
BOT = "railtech_test_bot"
PHONE = "+998901234567"


class FakeTransport:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []

    async def check(self, connection: SmtpConnection) -> SmtpCheck:
        return SmtpCheck("relay.test", False, 1)

    async def send(self, connection: SmtpConnection, to: str, subject: str, body: str) -> None:
        self.sent.append((to, subject, body))


class FakeBot:
    def __init__(self) -> None:
        self.sent: list[tuple[int, str]] = []
        self.error: Exception | None = None

    async def send_message(self, chat_id: int, text: str, **_: Any) -> Any:
        if self.error is not None:
            raise self.error
        self.sent.append((chat_id, text))
        return type("Sent", (), {"message_id": 900 + len(self.sent)})()


class Harness:
    def __init__(self) -> None:
        self.transport = FakeTransport()
        self.bot = FakeBot()
        self.queued_mail: list[int] = []
        self.follow_ups: list[WebLeadFollowUp] = []
        self.smtp = True
        self.container: Any = None
        self.notices: ClientNoticeService | None = None

    async def deliver_mail(self) -> None:
        for log_id in self.queued_mail:
            await self.container.mail_service.deliver(log_id)


@pytest.fixture
def harness() -> Harness:
    return Harness()


@pytest.fixture
def client(
    sessions: async_sessionmaker[AsyncSession], live_settings: Settings, harness: Harness
) -> Iterator[TestClient]:
    settings = live_settings.model_copy(update={"secrets_key": SecretStr(SECRETS_KEY)})
    app = create_app(settings)
    with TestClient(app) as test_client:
        container = app.state.container
        harness.container = container

        async def enqueue(email_log_id: int) -> int:
            harness.queued_mail.append(email_log_id)
            return email_log_id

        mail = MailService(
            container.session_factory,
            container.secrets_store,
            SecretCipher(SECRETS_KEY),
            settings,
            container.settings_service,
            harness.transport,
            enqueue,
        )
        container.__dict__["mail_service"] = mail

        async def bot_provider() -> Any:
            return harness.bot

        async def username() -> str:
            return BOT

        notices = ClientNoticeService(
            container.session_factory,
            container.settings_service,
            mail,
            bot_provider,
            username,
            link_key(settings.jwt_secret.get_secret_value().encode("utf-8")),
            settings,
        )
        harness.notices = notices
        container.__dict__["client_notice_service"] = notices

        async def record(follow_up: WebLeadFollowUp) -> None:
            harness.follow_ups.append(follow_up)

        container.__dict__["lead_intake"] = LeadIntakeService(
            container.session_factory,
            container.settings_service,
            settings.jwt_secret.get_secret_value().encode("utf-8"),
            notices=notices,
            on_web_lead=record,
        )
        yield test_client


async def connect_smtp(sessions: async_sessionmaker[AsyncSession], client: TestClient) -> None:
    """Коннектор «Почта» настроен: без него письмо клиенту не ставится (`smtp_not_configured`)."""
    admin, password = await make_user(sessions, "smtp-admin@railtech.uz", ["admin"])
    auth = login(client, admin.email, password)
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
        headers=auth,
    )
    assert response.status_code == 200, response.text


def post_web(client: TestClient, settings: Settings, **patch: Any) -> int:
    response = client.post("/api/v1/leads/web", json=web_body(settings, **patch))
    assert response.status_code == 202, response.text
    lead_id = response.json()["lead_id"]
    assert isinstance(lead_id, int)
    return lead_id


async def notice_of(sessions: async_sessionmaker[AsyncSession], lead_id: int) -> ClientNotice:
    async with sessions() as session:
        return (
            await session.scalars(select(ClientNotice).where(ClientNotice.lead_id == lead_id))
        ).one()


async def manager_headers(
    sessions: async_sessionmaker[AsyncSession], client: TestClient
) -> dict[str, str]:
    manager, password = await make_user(sessions, "card@railtech.uz", ["manager"])
    return login(client, manager.email, password)


# ── 1. Подтверждение клиенту ──────────────────────────────────────────────────────────────────


async def test_web_request_with_email_gets_a_confirmation_letter_visible_in_the_card(
    client: TestClient,
    sessions: async_sessionmaker[AsyncSession],
    live_settings: Settings,
    harness: Harness,
) -> None:
    await connect_smtp(sessions, client)
    lead_id = post_web(client, live_settings)

    notice = await notice_of(sessions, lead_id)
    assert (notice.kind, notice.channel, notice.status) == ("web_confirmation", "email", "queued")
    [follow_up] = harness.follow_ups
    assert follow_up == WebLeadFollowUp(lead_id, notice.id, follow_up.sla_due_at, repeat=False)

    assert harness.notices is not None
    assert await harness.notices.deliver(notice.id) == "queued"
    await harness.deliver_mail()
    [(to, subject, body)] = harness.transport.sent
    assert to == "a@rail.uz"
    assert subject == "Soʻrovingizni qabul qildik"  # язык формы — uz
    assert "Алишер" in body
    assert "Нужна интеграция POS с 1С" not in body, "письмо не цитирует текст запроса"
    for internal in ("лид", "сделк", "CRM", "crm"):
        assert internal not in body
    link = next(line for line in body.splitlines() if line.startswith("https://t.me/"))
    param = link.split("?start=")[1]
    key = link_key(live_settings.jwt_secret.get_secret_value().encode("utf-8"))
    assert verify_lead_link(key, param, datetime.now(UTC)) == lead_id

    auth = await manager_headers(sessions, client)
    confirmation = client.get(f"/api/v1/leads/{lead_id}", headers=auth).json()["confirmation"]
    assert confirmation["channel"] == "email"
    assert confirmation["status"] == "sent"
    assert confirmation["error"] is None


async def test_confirmation_is_not_sent_twice_by_a_repeated_job(
    client: TestClient,
    sessions: async_sessionmaker[AsyncSession],
    live_settings: Settings,
    harness: Harness,
) -> None:
    await connect_smtp(sessions, client)
    lead_id = post_web(client, live_settings)
    notice = await notice_of(sessions, lead_id)
    assert harness.notices is not None
    await harness.notices.deliver(notice.id)
    assert await harness.notices.deliver(notice.id) == "skipped"
    assert len(harness.queued_mail) == 1


async def test_failed_mail_is_shown_as_failed_with_words(
    client: TestClient,
    sessions: async_sessionmaker[AsyncSession],
    live_settings: Settings,
    harness: Harness,
) -> None:
    await connect_smtp(sessions, client)
    lead_id = post_web(client, live_settings)
    notice = await notice_of(sessions, lead_id)
    assert harness.notices is not None
    await harness.notices.deliver(notice.id)
    async with sessions() as session, session.begin():
        await session.execute(update(EmailLog).values(status="failed", error="refused"))

    auth = await manager_headers(sessions, client)
    confirmation = client.get(f"/api/v1/leads/{lead_id}", headers=auth).json()["confirmation"]
    assert confirmation["status"] == "failed"
    assert confirmation["error"] == "email_failed"
    assert "почтовый сервер отказал" in confirmation["error_text"]


async def test_without_the_mail_connector_the_card_says_so(
    client: TestClient,
    sessions: async_sessionmaker[AsyncSession],
    live_settings: Settings,
    harness: Harness,
) -> None:
    lead_id = post_web(client, live_settings)
    notice = await notice_of(sessions, lead_id)
    assert harness.notices is not None
    assert await harness.notices.deliver(notice.id) == "skipped"

    auth = await manager_headers(sessions, client)
    confirmation = client.get(f"/api/v1/leads/{lead_id}", headers=auth).json()["confirmation"]
    assert (confirmation["status"], confirmation["error"]) == ("skipped", "smtp_not_configured")
    assert "Почта не настроена" in confirmation["error_text"]


async def test_phone_only_request_cannot_be_confirmed_and_the_manager_is_told_to_call(
    client: TestClient,
    sessions: async_sessionmaker[AsyncSession],
    live_settings: Settings,
    harness: Harness,
) -> None:
    lead_id = post_web(client, live_settings, email=None)

    notice = await notice_of(sessions, lead_id)
    assert (notice.channel, notice.status, notice.error) == ("none", "skipped", "no_channel")
    [follow_up] = harness.follow_ups
    assert follow_up.notice_id is None, "слать нечем — задача отправки не ставится"
    auth = await manager_headers(sessions, client)
    confirmation = client.get(f"/api/v1/leads/{lead_id}", headers=auth).json()["confirmation"]
    assert "Позвоните клиенту" in confirmation["error_text"]


async def test_known_telegram_lead_gets_the_confirmation_in_the_bot(
    client: TestClient,
    sessions: async_sessionmaker[AsyncSession],
    live_settings: Settings,
    harness: Harness,
) -> None:
    async with sessions() as session, session.begin():
        lead, _, _ = await repo.create_lead_with_identity(
            session,
            tg_user_id=7700,
            username="alisher",
            first_name="Алишер",
            chat_id=7700,
            language="ru",
            identity=None,
        )
        lead.phone_e164 = PHONE
        lead.email = "a@rail.uz"
        lead_id = lead.id

    assert post_web(client, live_settings, language="ru") == lead_id
    notice = await notice_of(sessions, lead_id)
    assert (notice.channel, notice.status) == ("telegram", "queued")
    assert harness.follow_ups[0].repeat is True

    assert harness.notices is not None
    assert await harness.notices.deliver(notice.id) == "sent"
    [(chat, text)] = harness.bot.sent
    assert chat == 7700
    assert "Мы получили ваш запрос" in text
    assert harness.queued_mail == [], "бот ушёл — письмо не нужно"
    async with sessions() as session:
        said = (
            await session.scalars(
                select(Message.text).where(Message.role == "bot").order_by(Message.id.desc())
            )
        ).first()
    assert said == text, "сообщение бота видно менеджеру в переписке"


async def test_blocked_bot_falls_back_to_the_letter(
    client: TestClient,
    sessions: async_sessionmaker[AsyncSession],
    live_settings: Settings,
    harness: Harness,
) -> None:
    await connect_smtp(sessions, client)
    async with sessions() as session, session.begin():
        lead, _, _ = await repo.create_lead_with_identity(
            session,
            tg_user_id=7701,
            username=None,
            first_name="Б",
            chat_id=7701,
            language="ru",
            identity=None,
        )
        lead.phone_e164, lead.email = PHONE, "a@rail.uz"
    post_web(client, live_settings)
    notice = await notice_of(sessions, 1)
    harness.bot.error = TelegramForbiddenError(
        method=SendMessage(chat_id=7701, text="x"), message="Forbidden: bot was blocked by the user"
    )
    assert harness.notices is not None

    assert await harness.notices.deliver(notice.id) == "queued"

    fresh = await notice_of(sessions, 1)
    assert fresh.channel == "email"
    assert fresh.detail["telegram_failed"] == "telegram_blocked"
    assert len(harness.queued_mail) == 1


async def test_blocked_bot_without_email_is_a_failure_with_words(
    client: TestClient,
    sessions: async_sessionmaker[AsyncSession],
    live_settings: Settings,
    harness: Harness,
) -> None:
    async with sessions() as session, session.begin():
        lead, _, _ = await repo.create_lead_with_identity(
            session,
            tg_user_id=7702,
            username=None,
            first_name="В",
            chat_id=7702,
            language="ru",
            identity=None,
        )
        lead.phone_e164 = PHONE
    post_web(client, live_settings, email=None)
    notice = await notice_of(sessions, 1)
    harness.bot.error = TelegramForbiddenError(
        method=SendMessage(chat_id=7702, text="x"), message="Forbidden"
    )
    assert harness.notices is not None
    assert await harness.notices.deliver(notice.id) == "failed"

    fresh = await notice_of(sessions, 1)
    assert (fresh.status, fresh.error) == ("failed", "telegram_blocked")


async def test_network_error_is_retried_then_falls_back(
    client: TestClient,
    sessions: async_sessionmaker[AsyncSession],
    live_settings: Settings,
    harness: Harness,
) -> None:
    await connect_smtp(sessions, client)
    async with sessions() as session, session.begin():
        lead, _, _ = await repo.create_lead_with_identity(
            session,
            tg_user_id=7703,
            username=None,
            first_name="Г",
            chat_id=7703,
            language="ru",
            identity=None,
        )
        lead.phone_e164, lead.email = PHONE, "a@rail.uz"
    post_web(client, live_settings)
    notice = await notice_of(sessions, 1)
    harness.bot.error = TelegramNetworkError(
        method=SendMessage(chat_id=7703, text="x"), message="down"
    )
    assert harness.notices is not None

    for attempt in range(MAX_TELEGRAM_ATTEMPTS - 1):
        with pytest.raises(TelegramNetworkError):
            await harness.notices.deliver(notice.id)
        assert (await notice_of(sessions, 1)).attempts == attempt + 1
    assert await harness.notices.deliver(notice.id) == "queued"
    assert (await notice_of(sessions, 1)).channel == "email"

    harness.bot.error = None
    assert harness.bot.sent == []


# ── 2. Срок первого ответа и сообщение менеджерам ──────────────────────────────────────────────


async def test_new_web_lead_has_a_first_response_deadline_from_settings(
    client: TestClient,
    sessions: async_sessionmaker[AsyncSession],
    live_settings: Settings,
    harness: Harness,
) -> None:
    lead_id = post_web(client, live_settings)
    async with sessions() as session:
        lead = await session.get(Lead, lead_id)
        assert lead is not None
        due = lead.first_response_due_at
    assert due is not None
    assert due > datetime.now(UTC)
    assert harness.follow_ups[0].sla_due_at == due

    auth = await manager_headers(sessions, client)
    detail = client.get(f"/api/v1/leads/{lead_id}", headers=auth).json()
    assert detail["first_response_due_at"] is not None
    assert detail["first_response_overdue"] is False
    inbox = client.get("/api/v1/inbox", headers=auth).json()
    assert [row["id"] for row in inbox["unassigned"]] == [lead_id], "запрос виден в «Моей очереди»"


async def test_overdue_is_reported_once_and_only_while_nobody_took_the_lead(
    client: TestClient,
    sessions: async_sessionmaker[AsyncSession],
    live_settings: Settings,
) -> None:
    first = post_web(client, live_settings)
    second = post_web(client, live_settings, phone="+998907777777", email="b@rail.uz")
    later = datetime.now(UTC) + timedelta(days=3)
    manager, _ = await make_user(sessions, "taker@railtech.uz", ["manager"])
    async with sessions() as session, session.begin():
        await session.execute(
            update(Lead).where(Lead.id == second).values(assigned_user_id=manager.id)
        )

    assert await web_lead_sla.mark_overdue(sessions, first, datetime.now(UTC)) is False, (
        "ещё не срок"
    )
    assert await web_lead_sla.mark_overdue(sessions, first, later) is True
    assert await web_lead_sla.mark_overdue(sessions, first, later) is False, (
        "напоминание — один раз"
    )
    assert await web_lead_sla.mark_overdue(sessions, second, later) is False, "лид взяли"

    async with sessions() as session, session.begin():
        await session.execute(
            update(Lead)
            .where(Lead.id == first)
            .values(first_response_due_at=datetime.now(UTC) - timedelta(hours=1))
        )
    auth = await manager_headers(sessions, client)
    detail = client.get(f"/api/v1/leads/{first}", headers=auth).json()
    assert detail["first_response_overdue"] is True


async def test_new_web_lead_is_sent_to_subscribed_managers_in_telegram(
    client: TestClient,
    sessions: async_sessionmaker[AsyncSession],
    live_settings: Settings,
) -> None:
    lead_id = post_web(client, live_settings, company="ООО <Рельс>")
    subscribed, _ = await make_user(sessions, "sub@railtech.uz", ["manager"])
    silent, _ = await make_user(sessions, "silent@railtech.uz", ["manager"])
    no_telegram, _ = await make_user(sessions, "nt@railtech.uz", ["manager"])
    async with sessions() as session, session.begin():
        await session.execute(update(User).where(User.id == subscribed.id).values(tg_user_id=8001))
        await session.execute(
            update(User).where(User.id == silent.id).values(tg_user_id=8002, notify_leads=False)
        )
        assert no_telegram.id

    bot = FakeSender()
    delivered = await StaffNotifier(sessions, bot).web_lead(lead_id, "https://crm.example.com", 15)

    assert delivered == 1
    [(chat, text)] = bot.sent
    assert chat == 8001
    assert "Новый запрос с сайта" in text
    assert "ООО &lt;Рельс&gt;" in text
    assert f"https://crm.example.com/leads/{lead_id}" in text
    assert "15 мин" in text


async def test_overdue_reminder_goes_to_everyone_subscribed(
    client: TestClient,
    sessions: async_sessionmaker[AsyncSession],
    live_settings: Settings,
) -> None:
    lead_id = post_web(client, live_settings)
    one, _ = await make_user(sessions, "one@railtech.uz", ["manager"])
    two, _ = await make_user(sessions, "two@railtech.uz", ["admin"])
    async with sessions() as session, session.begin():
        await session.execute(update(User).where(User.id == one.id).values(tg_user_id=8101))
        await session.execute(update(User).where(User.id == two.id).values(tg_user_id=8102))
    bot = FakeSender()

    sent = await StaffNotifier(sessions, bot).web_lead(
        lead_id, "https://crm.example.com", 15, overdue=True
    )

    assert sent == 2
    assert {chat for chat, _ in bot.sent} == {8101, 8102}
    assert all("ждёт ответа" in text for _, text in bot.sent)


async def test_repeat_request_notifies_only_the_owner_when_a_human_leads_the_lead(
    client: TestClient,
    sessions: async_sessionmaker[AsyncSession],
    live_settings: Settings,
) -> None:
    lead_id = post_web(client, live_settings)
    owner, _ = await make_user(sessions, "owner@railtech.uz", ["manager"])
    other, _ = await make_user(sessions, "other@railtech.uz", ["manager"])
    async with sessions() as session, session.begin():
        await session.execute(update(User).where(User.id == owner.id).values(tg_user_id=8201))
        await session.execute(update(User).where(User.id == other.id).values(tg_user_id=8202))
        await session.execute(
            update(Lead)
            .where(Lead.id == lead_id)
            .values(assigned_user_id=owner.id, owner_mode="human")
        )
    post_web(client, live_settings, text="Ещё вопрос")
    bot = FakeSender()

    await StaffNotifier(sessions, bot).web_lead(lead_id, "https://crm.example.com", 15, repeat=True)

    assert [chat for chat, _ in bot.sent] == [8201]
    async with sessions() as session:
        notes = (await session.scalars(select(LeadNote.text))).all()
    assert any("Ещё вопрос" in note for note in notes)


async def test_erasing_the_lead_removes_the_confirmation_and_its_letter(
    client: TestClient,
    sessions: async_sessionmaker[AsyncSession],
    live_settings: Settings,
    harness: Harness,
) -> None:
    await connect_smtp(sessions, client)
    lead_id = post_web(client, live_settings)
    notice = await notice_of(sessions, lead_id)
    assert harness.notices is not None
    await harness.notices.deliver(notice.id)

    async with sessions() as session, session.begin():
        lead = await repo.get_lead(session, lead_id, for_update=True)
        assert lead is not None
        await repo.erase_lead(session, lead, datetime.now(UTC))

    async with sessions() as session:
        assert (await session.scalars(select(ClientNotice))).all() == []
        assert (
            await session.scalars(select(EmailLog).where(EmailLog.to_email == "a@rail.uz"))
        ).all() == []


async def test_repeat_request_of_an_unowned_lead_notifies_nobody_and_quotes_the_new_text(
    client: TestClient,
    sessions: async_sessionmaker[AsyncSession],
    live_settings: Settings,
) -> None:
    lead_id = post_web(client, live_settings)
    manager_a, _ = await make_user(sessions, "ua@railtech.uz", ["manager"])
    async with sessions() as session, session.begin():
        await session.execute(update(User).where(User.id == manager_a.id).values(tg_user_id=8301))
    post_web(client, live_settings, text="Ещё вопрос")
    bot = FakeSender()
    notifier = StaffNotifier(sessions, bot)

    assert await notifier.web_lead(lead_id, "https://crm.example.com", 15, repeat=True) == 0
    assert bot.sent == []

    async with sessions() as session, session.begin():
        await session.execute(
            update(Lead).where(Lead.id == lead_id).values(assigned_user_id=manager_a.id)
        )
    assert await notifier.web_lead(lead_id, "https://crm.example.com", 15, repeat=True) == 1
    assert "Ещё вопрос" in bot.sent[0][1], "повторный запрос — его текст, а не первый"


async def test_overdue_sweep_finds_a_deadline_that_moved_to_the_surviving_card(
    client: TestClient,
    sessions: async_sessionmaker[AsyncSession],
    live_settings: Settings,
) -> None:
    """Склейка с Telegram-карточкой удаляет лида, на которого поставлена отложенная задача."""
    web_id = post_web(client, live_settings)
    async with sessions() as session, session.begin():
        tg, _, _ = await repo.create_lead_with_identity(
            session,
            tg_user_id=7790,
            username=None,
            first_name="Т",
            chat_id=7790,
            language="ru",
            identity=None,
        )
        tg.created_at = datetime.now(UTC) - timedelta(days=1)  # Telegram-карточка старше — выживет
        identity = await repo.get_identity(session, 7790)
        assert identity is not None
        outcome = await merge_with_lead(session, identity, web_id)
        assert outcome is not None
        survivor = outcome.survivor_id
        lead = await session.get(Lead, survivor)
        assert lead is not None
        lead.first_response_due_at = datetime.now(UTC) - timedelta(minutes=1)
        lead.assigned_user_id = None

    assert await web_lead_sla.overdue_ids(sessions, datetime.now(UTC)) == [survivor]
    assert await web_lead_sla.mark_overdue(sessions, web_id, datetime.now(UTC)) is False
    assert await web_lead_sla.mark_overdue(sessions, survivor, datetime.now(UTC)) is True
    assert await web_lead_sla.overdue_ids(sessions, datetime.now(UTC)) == []
