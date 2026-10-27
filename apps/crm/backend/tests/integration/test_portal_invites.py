"""Приглашение клиента в кабинет (D1-9, Q-FIX23-1): итог при передаче, доставка ботом, повтор.

Менеджер видит в карточке клиента и лида: ушло ли приглашение, каким каналом, а если нет — причину
словами и канал, которым стоит повторить. Лид только с телефоном получает понятную ошибку, а не
молчание в логе.
"""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from aiogram.exceptions import TelegramForbiddenError
from aiogram.methods import SendMessage
from fastapi.testclient import TestClient
from rt_bus import Event
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bus.snapshots import contact_snapshot
from app.config import Settings
from app.domain.errors import Reason, UpstreamUnavailableError
from app.integrations.erp import HandoffPayload, HandoffResult, InviteResult
from app.main import create_app
from app.models.clients import Client, ClientContact
from app.models.leads import Lead, TelegramIdentity
from app.models.notices import ClientNotice
from app.services.erp_handoff import ErpHandoffService
from app.services.erp_invite_delivery import InviteDelivery
from app.services.portal_invites import PortalInviteService
from app.services.settings import SettingsService
from tests.bus_events import example_envelope
from tests.integration.crm_helpers import login, make_user

pytestmark = pytest.mark.integration

CONSENT_AT = datetime(2026, 10, 8, 9, 30, tzinfo=UTC)
CABINET = "https://cabinet.example.com"


class FakeErp:
    def __init__(
        self,
        *,
        sent_via: list[str] | None = None,
        error: str | None = None,
        invite: InviteResult | Exception | None = None,
    ) -> None:
        self.sent_via = ["email"] if sent_via is None else sent_via
        self.error = error
        self.invite = invite
        self.handoffs: list[HandoffPayload] = []
        self.invites: list[tuple[int, str, int | None]] = []

    async def handoff_client(
        self, payload: HandoffPayload, *, idempotency_key: str | None = None
    ) -> HandoffResult:
        self.handoffs.append(payload)
        return HandoffResult(7001, None, self.sent_via, CABINET, invite_error=self.error)

    async def invite_client(
        self, crm_client_id: int, channel: str, crm_contact_id: int | None
    ) -> InviteResult:
        self.invites.append((crm_client_id, channel, crm_contact_id))
        if isinstance(self.invite, Exception):
            raise self.invite
        return self.invite or InviteResult(["email"], None)


class FakeBot:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.error: Exception | None = None

    async def send_message(self, **kwargs: Any) -> Any:
        if self.error is not None:
            raise self.error
        self.sent.append(kwargs)
        return type("Sent", (), {"message_id": 1})()


async def seed(
    sessions: async_sessionmaker[AsyncSession],
    *,
    email: str | None = "ivan@client.uz",
    telegram: int | None = 5551,
    preferred: str | None = None,
    in_erp: bool = False,
    phone: str = "+998901112233",
) -> tuple[int, int, int]:
    """Клиент, его лид с Telegram и основной контакт → (клиент, лид, контакт)."""
    async with sessions() as session, session.begin():
        client = Client(name="ООО Логистик", erp_handoff_request=True)
        session.add(client)
        await session.flush()
        lead = Lead(
            display_name="Иван",
            stage="customer",
            owner_mode="bot",
            language="ru",
            client_id=client.id,
            email=email,
            phone_e164=phone,
            need_summary="Нужны вагоны",
            consent_given_at=CONSENT_AT,
            consent_version="2026-10-08",
        )
        session.add(lead)
        await session.flush()
        identity_id = None
        if telegram is not None:
            identity = TelegramIdentity(tg_user_id=telegram, lead_id=lead.id, tg_first_name="Иван")
            session.add(identity)
            await session.flush()
            identity_id = identity.id
        contact = ClientContact(
            client_id=client.id,
            full_name="Иван Иванов",
            email=email,
            phone_e164=phone,
            is_primary=True,
            telegram_identity_id=identity_id,
            preferred_channel=preferred,
        )
        session.add(contact)
        await session.flush()
        if in_erp:
            client.erp_company_id = 7001
        return client.id, lead.id, contact.id


async def hand_off(
    sessions: async_sessionmaker[AsyncSession], erp: FakeErp, ids: tuple[int, int, int]
) -> None:
    manager, _ = await make_user(sessions, f"h{ids[0]}@railtech.uz", ["manager"])
    outcome = await ErpHandoffService(sessions, erp).run(ids[0], ids[1], manager.id)
    assert outcome == "done"


async def notices(sessions: async_sessionmaker[AsyncSession]) -> list[ClientNotice]:
    async with sessions() as session:
        rows = await session.scalars(
            select(ClientNotice)
            .where(ClientNotice.kind == "portal_invite")
            .order_by(ClientNotice.id)
        )
        return list(rows)


# ── итог при передаче клиента в ERP ───────────────────────────────────────────────────────────


async def test_handoff_records_email_invite_as_sent(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    ids = await seed(sessions)
    erp = FakeErp(sent_via=["email"])
    await hand_off(sessions, erp, ids)

    [row] = await notices(sessions)
    assert (row.channel, row.status, row.error) == ("email", "sent", None)
    assert row.sent_at is not None
    assert row.contact_id == ids[2]


async def test_handoff_with_telegram_waits_for_the_bot(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    ids = await seed(sessions, email=None)
    erp = FakeErp(sent_via=["telegram"])
    await hand_off(sessions, erp, ids)

    [row] = await notices(sessions)
    assert (row.channel, row.status) == ("telegram", "queued")
    assert row.detail["telegram"] == "pending"


async def test_phone_only_contact_gets_an_understandable_error_not_a_silent_log_line(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """Q-FIX23-1: лид только с телефоном — приглашение не уйдёт; менеджер видит почему."""
    ids = await seed(sessions, email=None, telegram=None)
    erp = FakeErp(sent_via=[], error="CONTACT_TELEGRAM_REQUIRED")
    await hand_off(sessions, erp, ids)

    [row] = await notices(sessions)
    assert (row.status, row.error) == ("failed", "CONTACT_CHANNEL_REQUIRED")
    async with sessions() as session:
        view = await PortalInviteService(sessions, erp).current(session, ids[0])
    assert view is not None
    assert "только телефон" in (view.error_text or "")
    assert view.available_channels == []
    assert view.suggested_channel is None


async def test_failed_email_suggests_telegram_and_names_the_reason(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    ids = await seed(sessions)
    erp = FakeErp(sent_via=[], error="EMAIL_DELIVERY_FAILED")
    await hand_off(sessions, erp, ids)

    async with sessions() as session:
        view = await PortalInviteService(sessions, erp).current(session, ids[0])
    assert view is not None
    assert (view.status, view.error) == ("failed", "EMAIL_DELIVERY_FAILED")
    assert view.available_channels == ["email", "telegram"]
    assert view.suggested_channel == "telegram", "почта не ушла — предлагаем другой канал"
    assert "Письмо не ушло" in (view.error_text or "")


async def test_preferred_channel_of_the_contact_decides_where_the_invite_goes(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    ids = await seed(sessions, preferred="email")
    erp = FakeErp(sent_via=["email"])
    await hand_off(sessions, erp, ids)

    payload = erp.handoffs[0]
    assert payload.invite.channels == ["email"], "есть и Telegram, но выбрана почта"
    assert payload.contacts[0].preferred_channel == "email"


async def test_without_a_choice_the_invite_goes_to_all_channels_the_contact_has(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    ids = await seed(sessions)
    erp = FakeErp(sent_via=["email", "telegram"])
    await hand_off(sessions, erp, ids)

    assert erp.handoffs[0].invite.channels == ["telegram", "email"]
    [row] = await notices(sessions)
    assert (row.channel, row.status) == ("both", "sent")


# ── доставка ботом (событие invite.requested) ──────────────────────────────────────────────────


def delivery(
    sessions: async_sessionmaker[AsyncSession], bot: FakeBot | None, config: Settings, erp: FakeErp
) -> InviteDelivery:
    async def provider() -> Any:
        return bot

    return InviteDelivery(
        sessions,
        SettingsService(sessions, ttl_s=0),
        provider,
        config,
        PortalInviteService(sessions, erp),
    )


async def set_cabinet(sessions: async_sessionmaker[AsyncSession], url: str) -> None:
    await SettingsService(sessions, ttl_s=0).update(
        "company", {"name": "RailTech", "crm_base_url": "http://x", "cabinet_url": url}, None, None
    )


def invite_event(client_id: int, contact_id: int) -> Any:
    from app.bus.erp_event import parse_erp_event

    envelope = example_envelope("uz.railtech.erp.invite.requested.v1")
    envelope["data"]["crm_client_id"] = client_id
    envelope["data"]["payload"]["crm_contact_id"] = contact_id
    return parse_erp_event(Event.from_dict(envelope))


async def test_bot_sends_the_invite_with_an_open_cabinet_button_and_the_card_shows_it(
    sessions: async_sessionmaker[AsyncSession], live_settings: Settings
) -> None:
    ids = await seed(sessions, email=None)
    erp = FakeErp(sent_via=["telegram"])
    await hand_off(sessions, erp, ids)
    await set_cabinet(sessions, CABINET)
    bot = FakeBot()

    outcome = await delivery(sessions, bot, live_settings, erp).deliver(
        "evt-1", invite_event(ids[0], ids[2])
    )

    assert outcome == "processed"
    [sent] = bot.sent
    assert sent["chat_id"] == 5551
    assert "Иван Иванов" in sent["text"] or "кабинет" in sent["text"]
    button = sent["reply_markup"].inline_keyboard[0][0]
    assert button.text == "Открыть кабинет"
    assert button.web_app.url == CABINET, "Mini App: вход по Telegram-аккаунту, токенов нет"
    [row] = await notices(sessions)
    assert (row.status, row.error, row.detail["telegram"]) == ("sent", None, "sent")


async def test_blocked_bot_is_a_failure_with_words_and_the_email_suggestion(
    sessions: async_sessionmaker[AsyncSession], live_settings: Settings
) -> None:
    ids = await seed(sessions)
    erp = FakeErp(sent_via=["telegram"])
    await hand_off(sessions, erp, ids)
    await set_cabinet(sessions, CABINET)
    bot = FakeBot()
    bot.error = TelegramForbiddenError(
        method=SendMessage(chat_id=5551, text="x"), message="Forbidden"
    )

    outcome = await delivery(sessions, bot, live_settings, erp).deliver(
        "evt-2", invite_event(ids[0], ids[2])
    )

    assert outcome == "failed"
    async with sessions() as session:
        view = await PortalInviteService(sessions, erp).current(session, ids[0])
    assert view is not None
    assert (view.status, view.error) == ("failed", "telegram_blocked")
    assert "заблокировал бота" in (view.error_text or "")
    assert view.suggested_channel == "email"


async def test_failed_telegram_does_not_spoil_a_delivered_email(
    sessions: async_sessionmaker[AsyncSession], live_settings: Settings
) -> None:
    ids = await seed(sessions)
    erp = FakeErp(sent_via=["email", "telegram"])
    await hand_off(sessions, erp, ids)
    await set_cabinet(sessions, CABINET)
    bot = FakeBot()
    bot.error = TelegramForbiddenError(
        method=SendMessage(chat_id=5551, text="x"), message="Forbidden"
    )

    await delivery(sessions, bot, live_settings, erp).deliver("evt-3", invite_event(ids[0], ids[2]))

    [row] = await notices(sessions)
    assert (row.status, row.error) == ("sent", None), "письмо ушло — приглашение доставлено"
    assert row.detail["telegram_error"] == "telegram_blocked"


async def test_no_cabinet_address_is_reported_not_swallowed(
    sessions: async_sessionmaker[AsyncSession], live_settings: Settings
) -> None:
    ids = await seed(sessions, email=None)
    erp = FakeErp(sent_via=["telegram"])
    await hand_off(sessions, erp, ids)
    bot = FakeBot()

    assert (
        await delivery(sessions, bot, live_settings, erp).deliver(
            "evt-4", invite_event(ids[0], ids[2])
        )
        == "failed"
    )

    assert bot.sent == []
    [row] = await notices(sessions)
    assert row.error == "cabinet_not_configured"


async def test_event_for_a_contact_without_telegram_fails_without_a_message(
    sessions: async_sessionmaker[AsyncSession], live_settings: Settings
) -> None:
    ids = await seed(sessions, telegram=None)
    erp = FakeErp(sent_via=["email"])
    await hand_off(sessions, erp, ids)
    await set_cabinet(sessions, CABINET)
    bot = FakeBot()

    outcome = await delivery(sessions, bot, live_settings, erp).deliver(
        "evt-5", invite_event(ids[0], ids[2])
    )

    assert outcome == "failed"
    assert bot.sent == []


# ── API: карточка и повтор ────────────────────────────────────────────────────────────────────


@pytest.fixture
def client(live_settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(live_settings)) as test_client:
        yield test_client


def use_erp(client: TestClient, erp: FakeErp) -> None:
    container = client.app.state.container  # type: ignore[attr-defined]
    container.__dict__["portal_invites"] = PortalInviteService(container.session_factory, erp)


async def manager(
    sessions: async_sessionmaker[AsyncSession], client: TestClient, role: str = "manager"
) -> dict[str, str]:
    account, password = await make_user(sessions, f"{role}-api@railtech.uz", [role])
    return login(client, account.email, password)


async def test_client_card_shows_the_invitation_and_the_lead_card_too(
    sessions: async_sessionmaker[AsyncSession], client: TestClient
) -> None:
    ids = await seed(sessions, in_erp=True)
    erp = FakeErp(sent_via=[], error="EMAIL_DELIVERY_FAILED")
    await hand_off(sessions, erp, ids)
    use_erp(client, erp)
    auth = await manager(sessions, client)

    card = client.get(f"/api/v1/clients/{ids[0]}", headers=auth).json()["invitation"]
    lead = client.get(f"/api/v1/leads/{ids[1]}", headers=auth).json()["invitation"]

    assert card == lead
    assert card["status"] == "failed"
    assert card["error"] == "EMAIL_DELIVERY_FAILED"
    assert card["contact_name"] == "Иван Иванов"
    assert card["available_channels"] == ["email", "telegram"]
    assert card["suggested_channel"] == "telegram"
    assert card["can_resend"] is True


async def test_resend_by_another_channel_is_recorded_and_returned(
    sessions: async_sessionmaker[AsyncSession], client: TestClient
) -> None:
    ids = await seed(sessions, in_erp=True)
    erp = FakeErp(sent_via=[], error="EMAIL_DELIVERY_FAILED")
    await hand_off(sessions, erp, ids)
    erp.invite = InviteResult(["telegram"], None)
    use_erp(client, erp)
    auth = await manager(sessions, client)

    response = client.post(
        f"/api/v1/clients/{ids[0]}/invitation", json={"channel": "telegram"}, headers=auth
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["channel"], body["status"], body["sent_via"]) == (
        "telegram",
        "queued",
        ["telegram"],
    )
    assert erp.invites == [(ids[0], "telegram", ids[2])]
    assert len(await notices(sessions)) == 2, "история попыток сохраняется"
    assert (
        client.get(f"/api/v1/clients/{ids[0]}", headers=auth).json()["invitation"]["id"]
        == body["id"]
    )


async def test_resend_reports_the_erp_reason_in_words(
    sessions: async_sessionmaker[AsyncSession], client: TestClient
) -> None:
    ids = await seed(sessions, telegram=None, in_erp=True)
    erp = FakeErp(sent_via=["email"])
    await hand_off(sessions, erp, ids)
    erp.invite = InviteResult([], "CONTACT_TELEGRAM_REQUIRED")
    use_erp(client, erp)
    auth = await manager(sessions, client)

    body = client.post(
        f"/api/v1/clients/{ids[0]}/invitation", json={"channel": "telegram"}, headers=auth
    ).json()

    assert (body["status"], body["error"]) == ("failed", "CONTACT_TELEGRAM_REQUIRED")
    assert "ещё не писал боту" in body["error_text"]


async def test_resend_when_erp_is_down_is_a_recorded_failure_not_a_500(
    sessions: async_sessionmaker[AsyncSession], client: TestClient
) -> None:
    ids = await seed(sessions, in_erp=True)
    erp = FakeErp(sent_via=["email"])
    await hand_off(sessions, erp, ids)
    erp.invite = UpstreamUnavailableError("down", reason=Reason.ERP_UNAVAILABLE)
    use_erp(client, erp)
    auth = await manager(sessions, client)

    response = client.post(
        f"/api/v1/clients/{ids[0]}/invitation", json={"channel": "email"}, headers=auth
    )

    assert response.status_code == 200
    assert response.json()["error"] == "erp_unavailable"
    assert "ERP сейчас недоступна" in response.json()["error_text"]


async def test_resend_to_a_phone_only_contact_does_not_call_erp(
    sessions: async_sessionmaker[AsyncSession], client: TestClient
) -> None:
    ids = await seed(sessions, email=None, telegram=None, in_erp=True)
    erp = FakeErp()
    use_erp(client, erp)
    auth = await manager(sessions, client)

    body = client.post(
        f"/api/v1/clients/{ids[0]}/invitation", json={"channel": "both"}, headers=auth
    ).json()

    assert body["error"] == "CONTACT_CHANNEL_REQUIRED"
    assert erp.invites == []


async def test_resend_before_the_client_is_in_erp_is_a_409(
    sessions: async_sessionmaker[AsyncSession], client: TestClient
) -> None:
    ids = await seed(sessions, in_erp=False)
    use_erp(client, FakeErp())
    auth = await manager(sessions, client)

    response = client.post(
        f"/api/v1/clients/{ids[0]}/invitation", json={"channel": "email"}, headers=auth
    )

    assert response.status_code == 409
    assert response.json()["details"]["reason"] == "client_not_in_erp"


async def test_resend_is_checked_for_rights_contact_and_channel(
    sessions: async_sessionmaker[AsyncSession], client: TestClient
) -> None:
    ids = await seed(sessions, in_erp=True)
    other_client, _, other_contact = await seed(sessions, telegram=5552, in_erp=True)
    use_erp(client, FakeErp())
    viewer = await manager(sessions, client, "viewer")
    auth = await manager(sessions, client)
    url = f"/api/v1/clients/{ids[0]}/invitation"

    assert client.post(url, json={"channel": "email"}).status_code == 401
    assert client.post(url, json={"channel": "email"}, headers=viewer).status_code == 403
    assert client.post(url, json={"channel": "sms"}, headers=auth).status_code == 422
    assert (
        client.post(
            url, json={"channel": "email", "contact_id": other_contact}, headers=auth
        ).status_code
        == 404
    ), "контакт чужого клиента"
    assert (
        client.post(
            "/api/v1/clients/999999/invitation", json={"channel": "email"}, headers=auth
        ).status_code
        == 404
    )
    assert other_client != ids[0]


async def test_contact_preferred_channel_is_saved_validated_and_goes_into_the_erp_event(
    sessions: async_sessionmaker[AsyncSession], client: TestClient
) -> None:
    ids = await seed(sessions, in_erp=True)
    auth = await manager(sessions, client)
    url = f"/api/v1/clients/{ids[0]}/contacts/{ids[2]}"
    body = {"full_name": "Иван Иванов", "email": "ivan@client.uz", "is_primary": True}

    saved = client.put(url, json={**body, "preferred_channel": "telegram"}, headers=auth)
    assert saved.status_code == 200, saved.text
    contacts = client.get(f"/api/v1/clients/{ids[0]}/contacts", headers=auth).json()["contacts"]
    assert contacts[0]["preferred_channel"] == "telegram"
    assert (
        client.put(url, json={**body, "preferred_channel": "sms"}, headers=auth).status_code == 422
    )

    async with sessions() as session:
        contact = await session.get(ClientContact, ids[2])
        assert contact is not None
        snapshot = await contact_snapshot(session, contact)
    assert snapshot["preferred_channel"] == "telegram"
    cleared = client.put(url, json=body, headers=auth)
    assert cleared.status_code == 200
    async with sessions() as session:
        contact = await session.get(ClientContact, ids[2])
        assert contact is not None
        assert "preferred_channel" not in await contact_snapshot(session, contact)


# ── событие ERP раньше HTTP-ответа ERP ──────────────────────────────────────────────────────────


async def test_bot_result_that_beats_the_handoff_answer_is_not_lost(
    sessions: async_sessionmaker[AsyncSession], live_settings: Settings
) -> None:
    """`invite.requested` доходит до CRM раньше ответа ERP: итог не теряется, строка одна."""
    ids = await seed(sessions, email=None)
    erp = FakeErp(sent_via=["telegram"])
    await set_cabinet(sessions, CABINET)
    bot = FakeBot()

    await delivery(sessions, bot, live_settings, erp).deliver(
        "evt-r1", invite_event(ids[0], ids[2])
    )
    [orphan] = await notices(sessions)
    assert orphan.detail["orphan"] is True
    assert orphan.status == "sent"

    await hand_off(sessions, erp, ids)

    [row] = await notices(sessions)
    assert (row.status, row.error, row.detail["telegram"]) == ("sent", None, "sent")
    assert "orphan" not in row.detail


async def test_failed_bot_result_that_came_first_is_shown_with_its_reason(
    sessions: async_sessionmaker[AsyncSession], live_settings: Settings
) -> None:
    ids = await seed(sessions, email=None)
    erp = FakeErp(sent_via=["telegram"])
    # адрес кабинета не задан: бот не пишет и называет причину
    await delivery(sessions, FakeBot(), live_settings, erp).deliver(
        "evt-r2", invite_event(ids[0], ids[2])
    )

    await hand_off(sessions, erp, ids)

    [row] = await notices(sessions)
    assert (row.status, row.error) == ("failed", "cabinet_not_configured")


async def test_bot_result_that_beats_a_resend_answer_is_adopted_too(
    sessions: async_sessionmaker[AsyncSession], live_settings: Settings, client: TestClient
) -> None:
    ids = await seed(sessions, in_erp=True)
    erp = FakeErp(sent_via=["email"])
    await hand_off(sessions, erp, ids)
    await set_cabinet(sessions, CABINET)
    await delivery(sessions, FakeBot(), live_settings, erp).deliver(
        "evt-r3", invite_event(ids[0], ids[2])
    )
    erp.invite = InviteResult(["telegram"], None)
    use_erp(client, erp)
    auth = await manager(sessions, client)

    body = client.post(
        f"/api/v1/clients/{ids[0]}/invitation", json={"channel": "telegram"}, headers=auth
    ).json()

    assert body["status"] == "sent"
    rows = await notices(sessions)
    assert len(rows) == 2, "первая попытка и повтор; сирота подставлена и удалена"
    assert all("orphan" not in row.detail for row in rows)


async def test_a_stale_pending_invite_is_not_resolved_by_a_new_event(
    sessions: async_sessionmaker[AsyncSession], live_settings: Settings
) -> None:
    ids = await seed(sessions, email=None)
    erp = FakeErp(sent_via=["telegram"])
    await hand_off(sessions, erp, ids)
    async with sessions() as session, session.begin():
        await session.execute(
            update(ClientNotice).values(created_at=datetime.now(UTC) - timedelta(hours=2))
        )
    await set_cabinet(sessions, CABINET)

    await delivery(sessions, FakeBot(), live_settings, erp).deliver(
        "evt-r4", invite_event(ids[0], ids[2])
    )

    rows = await notices(sessions)
    assert [r.detail["telegram"] for r in rows] == ["pending", "sent"]
