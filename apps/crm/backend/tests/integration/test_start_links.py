"""Deep-link `/start` (D1-9): `web`, `deal_<id>`, подписанная ссылка из письма."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.start_link import LEAD_LINK_TTL, issue_lead_link
from app.models.auth import AuditLog
from app.models.clients import Client
from app.models.deals import Deal
from app.models.leads import Lead, LeadNote, TelegramIdentity
from app.repositories import leads as repo
from app.services.start_links import StartLinkService

pytestmark = pytest.mark.integration

KEY = b"integration-start-link-key-0123456789"
USER = 4401
OTHER_USER = 4402


@pytest.fixture
def links(sessions: async_sessionmaker[AsyncSession]) -> StartLinkService:
    return StartLinkService(sessions, KEY)


async def telegram_lead(
    sessions: async_sessionmaker[AsyncSession], tg_user_id: int = USER, language: str = "ru"
) -> int:
    async with sessions() as session, session.begin():
        lead, _, _ = await repo.create_lead_with_identity(
            session,
            tg_user_id=tg_user_id,
            username=None,
            first_name="Алишер",
            chat_id=tg_user_id,
            language=language,
            identity=None,
        )
        return lead.id


async def web_lead(sessions: async_sessionmaker[AsyncSession]) -> int:
    async with sessions() as session, session.begin():
        lead = Lead(
            display_name="Алишер",
            language="uz",
            source="web",
            email="a@rail.uz",
            owner_mode="paused",
        )
        session.add(lead)
        await session.flush()
        return lead.id


async def client_with_deal(
    sessions: async_sessionmaker[AsyncSession],
    tg_user_id: int,
    erp_deal_id: int,
    *,
    verified: bool = True,
) -> int:
    """Клиент CRM, чей Telegram привязан (и проверен менеджером), и зеркало его заявки в ERP."""
    async with sessions() as session, session.begin():
        client = Client(name=f"ООО {erp_deal_id}")
        session.add(client)
        await session.flush()
        session.add(
            Deal(client_id=client.id, title=f"Рельсы {erp_deal_id}", erp_deal_id=erp_deal_id)
        )
        identity = await repo.get_identity(session, tg_user_id)
        assert identity is not None
        identity.client_id = client.id
        if verified:
            identity.verified_at = datetime.now(UTC)
        return client.id


async def audit_actions(sessions: async_sessionmaker[AsyncSession]) -> list[str]:
    async with sessions() as session:
        return list((await session.scalars(select(AuditLog.action).order_by(AuditLog.id))).all())


# ── web ────────────────────────────────────────────────────────────────────────────────────────


async def test_start_web_marks_a_new_lead_as_coming_from_the_site(
    sessions: async_sessionmaker[AsyncSession], links: StartLinkService
) -> None:
    lead_id = await telegram_lead(sessions)

    result = await links.apply(USER, "web")

    assert result.texts == []
    async with sessions() as session:
        lead = await session.get(Lead, lead_id)
        assert lead is not None
        assert lead.source == "web"
    assert "lead.start_web" in await audit_actions(sessions)


async def test_start_web_does_not_relabel_a_lead_who_already_talked(
    sessions: async_sessionmaker[AsyncSession], links: StartLinkService
) -> None:
    lead_id = await telegram_lead(sessions)
    async with sessions() as session, session.begin():
        lead = await session.get(Lead, lead_id)
        assert lead is not None
        lead.last_lead_msg_at = datetime.now(UTC)

    await links.apply(USER, "web")

    async with sessions() as session:
        lead = await session.get(Lead, lead_id)
        assert lead is not None
        assert lead.source == "telegram"


# ── deal_<id> ──────────────────────────────────────────────────────────────────────────────────


async def test_start_deal_of_the_verified_client_is_bound_and_noted(
    sessions: async_sessionmaker[AsyncSession], links: StartLinkService
) -> None:
    lead_id = await telegram_lead(sessions)
    await client_with_deal(sessions, USER, 501)

    result = await links.apply(USER, "deal_501")

    assert result.texts == [
        "Вижу вашу заявку «Рельсы 501». Напишите, что хотите уточнить, — передам менеджеру."
    ]
    async with sessions() as session:
        note = (await session.scalars(select(LeadNote).where(LeadNote.lead_id == lead_id))).one()
    assert "Рельсы 501" in note.text
    assert note.visible_to_bot is False


async def test_start_deal_of_another_client_is_not_attached(
    sessions: async_sessionmaker[AsyncSession], links: StartLinkService
) -> None:
    """Ссылку кабинета может написать кто угодно: чужая заявка к чату не привязывается."""
    await telegram_lead(sessions, USER)
    await telegram_lead(sessions, OTHER_USER)
    await client_with_deal(sessions, USER, 501)
    await client_with_deal(sessions, OTHER_USER, 502)

    result = await links.apply(USER, "deal_502")

    assert result.texts == []
    assert "lead.start_deal_rejected" in await audit_actions(sessions)
    async with sessions() as session:
        assert (await session.scalars(select(LeadNote))).all() == []


@pytest.mark.parametrize("payload", ["deal_999", "deal_0"])
async def test_start_deal_that_does_not_exist_is_ignored(
    sessions: async_sessionmaker[AsyncSession], links: StartLinkService, payload: str
) -> None:
    await telegram_lead(sessions)
    await client_with_deal(sessions, USER, 501)
    assert (await links.apply(USER, payload)).texts == []


async def test_start_deal_from_an_unverified_telegram_is_ignored(
    sessions: async_sessionmaker[AsyncSession], links: StartLinkService
) -> None:
    await telegram_lead(sessions)
    await client_with_deal(sessions, USER, 501, verified=False)
    assert (await links.apply(USER, "deal_501")).texts == []


async def test_start_deal_from_a_stranger_telegram_is_ignored(
    sessions: async_sessionmaker[AsyncSession], links: StartLinkService
) -> None:
    await telegram_lead(sessions, USER)
    await telegram_lead(sessions, OTHER_USER)
    await client_with_deal(sessions, USER, 501)
    assert (await links.apply(OTHER_USER, "deal_501")).texts == []


# ── lead_<подпись> ──────────────────────────────────────────────────────────────────────────


async def test_signed_link_joins_the_telegram_chat_to_the_web_request(
    sessions: async_sessionmaker[AsyncSession], links: StartLinkService
) -> None:
    web_id = await web_lead(sessions)
    tg_id = await telegram_lead(sessions)
    link = issue_lead_link(KEY, web_id, datetime.now(UTC))

    result = await links.apply(USER, link)

    assert len(result.texts) == 1
    assert any(word in result.texts[0] for word in ("связан", "bogʻlandi", "linked"))
    async with sessions() as session:
        identity = await repo.get_identity(session, USER)
        assert identity is not None
        assert identity.lead_id in {web_id, tg_id}
        alive = (await session.scalars(select(Lead.id))).all()
    assert len(alive) == 1, "две карточки стали одной"
    assert alive[0] == identity.lead_id
    assert "lead.start_link_bound" in await audit_actions(sessions)


async def test_signed_link_works_once(
    sessions: async_sessionmaker[AsyncSession], links: StartLinkService
) -> None:
    web_id = await web_lead(sessions)
    await telegram_lead(sessions, USER)
    await telegram_lead(sessions, OTHER_USER)
    link = issue_lead_link(KEY, web_id, datetime.now(UTC))

    assert len((await links.apply(USER, link)).texts) == 1
    second = await links.apply(OTHER_USER, link)

    assert len(second.texts) == 1
    assert "устарела" in second.texts[0] or "eskirgan" in second.texts[0]
    async with sessions() as session:
        other = await repo.get_identity(session, OTHER_USER)
        mine = await repo.get_identity(session, USER)
        assert other is not None
        assert mine is not None
        assert other.lead_id != mine.lead_id, "чужой аккаунт к чужому запросу не склеился"


@pytest.mark.parametrize("age", [timedelta(hours=1), timedelta(days=30)])
async def test_expired_or_forged_links_do_nothing(
    sessions: async_sessionmaker[AsyncSession], links: StartLinkService, age: timedelta
) -> None:
    web_id = await web_lead(sessions)
    await telegram_lead(sessions)
    old = issue_lead_link(KEY, web_id, datetime.now(UTC) - LEAD_LINK_TTL - age)
    forged = issue_lead_link(b"another-key-another-key-another-key", web_id, datetime.now(UTC))

    for link in (old, forged):
        assert len((await links.apply(USER, link)).texts) == 1
    async with sessions() as session:
        assert len((await session.scalars(select(Lead.id))).all()) == 2, "ничего не склеилось"


async def test_signed_link_does_not_attach_a_request_to_a_client_chat(
    sessions: async_sessionmaker[AsyncSession], links: StartLinkService
) -> None:
    web_id = await web_lead(sessions)
    await telegram_lead(sessions)
    async with sessions() as session, session.begin():
        client = Client(name="ООО Клиент")
        session.add(client)
        await session.flush()
        identity = await repo.get_identity(session, USER)
        assert identity is not None
        assert identity.lead_id is not None
        lead = await repo.get_lead(session, identity.lead_id)
        assert lead is not None
        lead.client_id = client.id

    result = await links.apply(USER, issue_lead_link(KEY, web_id, datetime.now(UTC)))

    assert len(result.texts) == 1
    async with sessions() as session:
        assert len((await session.scalars(select(Lead.id))).all()) == 2


async def test_unknown_payloads_and_users_are_silent(
    sessions: async_sessionmaker[AsyncSession], links: StartLinkService
) -> None:
    await telegram_lead(sessions)
    for payload in (None, "", "quote_7", "invite_x", "deal_x"):
        assert (await links.apply(USER, payload)).texts == []
    assert (await links.apply(777000, "web")).texts == [], "аккаунта нет в базе"
    async with sessions() as session:
        assert (await session.scalars(select(TelegramIdentity.id))).all()
