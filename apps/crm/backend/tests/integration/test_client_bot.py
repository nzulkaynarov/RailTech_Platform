"""Интерфейс бота по статусу (Q-011, Q-020): меню, /docs, /request, /status, номер."""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.clients import Client, Document, DocumentAccessLog, ServiceRequest
from app.models.leads import Lead, Setting, TelegramIdentity
from app.models.qualification import Escalation
from app.schemas.settings import EscalationSettings
from app.services.client_bot import HANDOFF_PENDING, PHONE_ASKED, ClientBotService
from app.services.conversation import ConversationService, Incoming
from app.services.notification_data import load_card
from app.services.settings import SettingsService
from tests.integration.test_customer import USER, customer, service
from tests.unit.agents.fakes import ReplayModel

pytestmark = pytest.mark.integration
__all__ = ["service"]  # фикстура диалогового сервиса из сценария C5

Service = tuple[ConversationService, ReplayModel, list[str]]


def bot_service(sessions: async_sessionmaker[AsyncSession]) -> ClientBotService:
    async def presign(key: str, ttl_s: int) -> str:
        return f"http://s3.test/{key}?ttl={ttl_s}"

    return ClientBotService(sessions, SettingsService(sessions, ttl_s=0), presign)


async def test_prospect_menu_and_client_commands_refused(
    service: Service, sessions: async_sessionmaker[AsyncSession]
) -> None:
    svc, _, _ = service
    await svc.start(Incoming(tg_user_id=USER, chat_id=USER, text="/start", language_code="ru"))
    await svc.accept_consent(USER)
    bot = bot_service(sessions)
    status = await bot.status(USER)
    assert (status.variant, status.client_id) == ("prospect", None)
    assert await bot.documents(USER) is None
    assert await bot.request_status(USER) is None
    assert await bot.create_request(USER, "Касса не печатает") is None


async def test_client_documents_request_and_status(
    service: Service, sessions: async_sessionmaker[AsyncSession]
) -> None:
    svc, _, _ = service
    client_id = await customer(sessions, svc)
    bot = bot_service(sessions)
    assert (await bot.status(USER)).variant == "client"
    docs = await bot.documents(USER)
    assert docs is not None
    assert docs[0][1].startswith("Договор поставки №15")
    async with sessions() as session, session.begin():
        stranger = Client(name="Чужая компания")
        session.add(stranger)
        await session.flush()
        other = Document(
            client_id=stranger.id, type="act", title="Чужой", filename="x.pdf",
            mime="application/pdf", size_bytes=1, storage_key="k/x",
        )  # fmt: skip
        session.add(other)
        await session.flush()
        foreign_id = other.id
    assert await bot.document(USER, docs[0][0] + 999) is None  # несуществующий id
    assert await bot.document(USER, foreign_id) is None  # чужой id в callback кнопки (BOT-07)
    out = await bot.document(USER, docs[0][0])
    assert out is not None
    assert out.document is not None
    assert out.document["url"] == "http://s3.test/k/1?ttl=600"
    async with sessions() as session:
        assert len((await session.scalars(select(DocumentAccessLog))).all()) == 1
    assert "нет" in (await bot.request_status(USER) or "").lower()
    created = await bot.create_request(USER, "Нужен акт сверки за сентябрь")
    assert created is not None
    assert "передан менеджеру" in created
    async with sessions() as session:
        request = (await session.scalars(select(ServiceRequest))).one()
        escalation = (await session.scalars(select(Escalation))).one()
    assert (request.client_id, request.status) == (client_id, "open")
    assert "service_request" in escalation.reason_codes
    assert "акт сверки" in (await bot.request_status(USER) or "")


async def test_phone_flag_and_save(
    service: Service, sessions: async_sessionmaker[AsyncSession]
) -> None:
    svc, _, _ = service
    await svc.start(Incoming(tg_user_id=USER, chat_id=USER, text="/start", language_code="ru"))
    await svc.accept_consent(USER)
    bot = bot_service(sessions)
    async with sessions() as session, session.begin():
        lead = (await session.scalars(select(Lead))).one()
        lead.stage = "qualified"
    assert (await bot.status(USER)).ask_phone
    await bot.mark_phone_asked(USER)
    assert not (await bot.status(USER)).ask_phone  # второй раз не спрашиваем
    await bot.save_phone(USER, "+998901234567")
    async with sessions() as session:
        identity = (await session.scalars(select(TelegramIdentity))).one()
        lead = (await session.scalars(select(Lead))).one()
    assert identity.phone_e164 == "+998901234567"
    assert PHONE_ASKED in lead.qualification


async def test_human_request_without_phone_waits_then_hands_off_with_phone(
    service: Service, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """Решение владельца 2026-10-12: просьба лида — сначала номер, затем та же передача."""
    svc, _, _ = service
    await svc.start(Incoming(tg_user_id=USER, chat_id=USER, text="/start", language_code="ru"))
    await svc.accept_consent(USER)
    bot = bot_service(sessions)
    assert await bot.hold_handoff_for_phone(USER) == "ru"
    async with sessions() as session:
        lead = (await session.scalars(select(Lead))).one()
        assert (await session.scalars(select(Escalation))).first() is None
    assert HANDOFF_PENDING in lead.qualification
    assert PHONE_ASKED in lead.qualification  # middleware не спросит второй раз тем же ходом
    assert lead.owner_mode == "bot"
    assert await bot.take_pending_handoff(USER)
    assert not await bot.take_pending_handoff(USER)  # пометка снимается один раз
    await bot.save_phone(USER, "+998901234567")
    assert await bot.hold_handoff_for_phone(USER) is None  # номер есть — передаём сразу
    await svc.handle_message(Incoming(USER, USER, "📇 Азиз", human_requested=True))
    settings = SettingsService(sessions, ttl_s=0, platform_url="https://platform.example.com")
    cfg = await settings.get()
    async with sessions() as session:
        escalation = (await session.scalars(select(Escalation))).one()
        loaded = await load_card(session, escalation.id, cfg, await settings.links())
    assert escalation.reason_codes == ["human_requested"]
    assert loaded is not None
    assert loaded[1].phone == "+998901234567"
    # ссылка карточки в канале ведёт в Платформу, а не в старую CRM (B-009)
    assert loaded[1].crm_url == (
        f"https://platform.example.com/crm/leads?lead=L-{loaded[1].lead_id:04d}&panel=open&tab=card"
    )


async def test_human_request_gate_can_be_switched_off(
    service: Service, sessions: async_sessionmaker[AsyncSession]
) -> None:
    svc, _, _ = service
    await svc.start(Incoming(tg_user_id=USER, chat_id=USER, text="/start", language_code="ru"))
    await svc.accept_consent(USER)
    off = EscalationSettings(require_phone_for_human_request=False).model_dump(mode="json")
    async with sessions() as session, session.begin():
        session.add(Setting(key="escalation", value=off))
    assert await bot_service(sessions).hold_handoff_for_phone(USER) is None
