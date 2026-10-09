"""Сценарий C5: клиент просит документ — бот находит у этого клиента и отдаёт файл."""

from collections.abc import AsyncIterator
from contextlib import AsyncExitStack
from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient
from pydantic import AnyHttpUrl
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.dialog.graph import DialogAgent
from app.agents.llm import ToolCall
from app.agents.mcp_client import McpToolClient
from app.config import Settings
from app.container import Container
from app.domain.errors import ConflictError
from app.main import create_app
from app.mcp import crm_server, docs_server, kb_server
from app.mcp.common import build_app
from app.models.clients import Client, Document, DocumentAccessLog, ServiceRequest
from app.models.leads import Lead, TelegramIdentity
from app.models.qualification import Escalation
from app.security.principal import Principal
from app.services.clients import ClientService
from app.services.conversation import ConversationService, Incoming
from app.services.documents import DocumentService
from app.services.lead_messenger import LeadMessenger
from app.services.settings import SettingsService
from tests.fakes import FakeEmbedder
from tests.integration.crm_helpers import FakeSender, escalated_lead, login, make_user
from tests.integration.servers import free_port, running
from tests.integration.test_docs_mcp import FakeStorage
from tests.integration.test_kb_ingest import FakeConverter, MemoryStorage
from tests.unit.agents.fakes import ReplayModel, reply

pytestmark = pytest.mark.integration
USER = 8800


@pytest.fixture
async def service(
    sessions: async_sessionmaker[AsyncSession], live_settings: Settings
) -> AsyncIterator[tuple[ConversationService, ReplayModel, list[str]]]:
    container = Container(live_settings)
    container.__dict__["session_factory"] = sessions
    container.__dict__["embedder"] = FakeEmbedder()
    container.__dict__["storage"] = FakeStorage()
    activity: list[str] = []
    async with AsyncExitStack() as stack:
        urls = {}
        for name, module in (("kb", kb_server), ("crm", crm_server), ("docs", docs_server)):
            port = free_port()
            urls[name] = await stack.enter_async_context(
                running(build_app(module.create_server(container), f"{name}-mcp", port), port)
            )
        config = live_settings.model_copy(
            update={f"{k}_mcp_url": AnyHttpUrl(v) for k, v in urls.items()}
        )
        model = ReplayModel()

        async def on_activity(lead_id: int) -> None:
            activity.append(f"qualify-{lead_id}")

        svc = ConversationService(
            sessions,
            SettingsService(sessions, ttl_s=0),
            DialogAgent(McpToolClient(config), model),
            config.agent_context_key_bytes,
            on_activity=on_activity,
        )
        yield svc, model, activity


async def customer(sessions: async_sessionmaker[AsyncSession], svc: ConversationService) -> int:
    await svc.start(Incoming(tg_user_id=USER, chat_id=USER, text="/start", language_code="ru"))
    await svc.accept_consent(USER)
    async with sessions() as session, session.begin():
        client = Client(name="Альфа")
        session.add(client)
        await session.flush()
        identity = (await session.scalars(select(TelegramIdentity))).one()
        identity.client_id, identity.verified_at = client.id, datetime.now(UTC)
        lead = await session.get(Lead, identity.lead_id)
        assert lead is not None
        lead.stage, lead.client_id = "customer", client.id
        session.add(
            Document(
                client_id=client.id,
                type="contract",
                title="Договор поставки №15",
                number="15",
                doc_date=date(2026, 7, 14),
                storage_key="k/1",
                filename="dogovor.pdf",
                mime="application/pdf",
                size_bytes=10,
            )
        )
        return client.id


def msg(text: str) -> Incoming:
    return Incoming(tg_user_id=USER, chat_id=USER, text=text)


async def test_document_is_delivered_without_model(
    service: tuple[ConversationService, ReplayModel, list[str]],
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    svc, model, activity = service
    await customer(sessions, svc)
    out = await svc.handle_message(msg("Пришлите договор, который мы заключали в июле"))
    assert model.requests == []
    assert out[-1].document is not None
    assert out[-1].document["filename"] == "dogovor.pdf"
    assert "Договор поставки" in out[-1].text
    assert activity == []  # клиент: квалификатор не запускается
    async with sessions() as session:
        assert (await session.scalars(select(DocumentAccessLog))).one().accessed_by_type == "bot"


async def test_missing_document_goes_to_manager(
    service: tuple[ConversationService, ReplayModel, list[str]],
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    svc, _, _ = service
    await customer(sessions, svc)
    await svc.handle_message(msg("Пришлите акт за март"))
    async with sessions() as session:
        escalation = (await session.scalars(select(Escalation))).one()
        lead = (await session.scalars(select(Lead))).one()
    assert escalation.reason_codes == ["document_not_found"]
    assert (lead.stage, lead.owner_mode) == ("customer", "paused")  # клиент остаётся клиентом


async def test_service_request_via_tool(
    service: tuple[ConversationService, ReplayModel, list[str]],
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    svc, model, _ = service
    client_id = await customer(sessions, svc)
    call = ToolCall(
        id="s1", name="create_service_request", arguments={"summary": "Касса не печатает чеки"}
    )
    model.responses += [reply("", call), reply("Передал запрос менеджеру.")]
    await svc.handle_message(msg("У нас касса не печатает чеки"))
    system = model.requests[0][0]["content"]
    assert "сервисный ассистент" in system
    async with sessions() as session:
        request = (await session.scalars(select(ServiceRequest))).one()
        escalation = (await session.scalars(select(Escalation))).one()
        lead = (await session.scalars(select(Lead))).one()
    assert (request.client_id, request.summary) == (client_id, "Касса не печатает чеки")
    assert (escalation.reason_codes, escalation.priority) == (["service_request"], "info")
    assert lead.owner_mode == "bot"  # info не глушит бота (ADR-0015)

    sender = FakeSender()
    clients = ClientService(
        sessions, SettingsService(sessions, ttl_s=0), LeadMessenger(sessions, sender)
    )
    admin, _ = await make_user(sessions, "boss@railtech.uz", ["admin"])
    who = Principal(admin.id, "Босс", ("admin",))
    await clients.close_service_request(who, request.id, "Инженер приедет завтра в 10:00")
    assert sender.sent[-1][1] == (
        "По вашему запросу «Касса не печатает чеки»: Инженер приедет завтра в 10:00"
    )
    async with sessions() as session:
        escalation = (await session.scalars(select(Escalation))).one()
    assert (escalation.status, escalation.outcome) == ("closed", "service_request_closed")
    with pytest.raises(ConflictError):
        await clients.close_service_request(who, request.id, "ещё раз")


async def test_unverified_identity_stays_prospect(
    service: tuple[ConversationService, ReplayModel, list[str]],
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    svc, model, activity = service
    await customer(sessions, svc)
    async with sessions() as session, session.begin():
        identity = (await session.scalars(select(TelegramIdentity))).one()
        identity.verified_at = None
    model.responses.append(reply("Подскажу по продуктам."))
    out = await svc.handle_message(msg("Пришлите договор за июль"))
    assert out[-1].document is None
    assert activity  # prospect → квалификатор
    async with sessions() as session:
        assert (await session.scalars(select(DocumentAccessLog))).first() is None


async def test_crm_link_telegram_and_make_customer(
    sessions: async_sessionmaker[AsyncSession], live_settings: Settings
) -> None:
    lead_id = await escalated_lead(sessions, tg_user_id=4242)
    manager, password = await make_user(sessions, "m@railtech.uz", ["manager"])
    viewer, vpassword = await make_user(sessions, "v@railtech.uz", ["viewer"])
    with TestClient(create_app(live_settings)) as client:
        headers = login(client, manager.email, password)
        client.post(f"/api/v1/leads/{lead_id}/actions/take", headers=headers)
        early = client.post(
            f"/api/v1/leads/{lead_id}/actions/make_customer",
            json={"new_client_name": "ООО Ромашка"},
            headers=headers,
        )
        assert early.status_code == 409
        client.post(f"/api/v1/leads/{lead_id}/actions/close_won", json={}, headers=headers)
        made = client.post(
            f"/api/v1/leads/{lead_id}/actions/make_customer",
            json={"new_client_name": "ООО Ромашка"},
            headers=headers,
        )
        assert made.status_code == 201
        client_id = made.json()["id"]
        detail = client.get(f"/api/v1/clients/{client_id}", headers=headers).json()
        assert [i["tg_user_id"] for i in detail["identities"]] == [4242]
        assert detail["identities"][0]["verified_at"]
        unknown = client.post(
            f"/api/v1/clients/{client_id}/telegram", json={"tg_user_id": 1}, headers=headers
        )
        assert unknown.status_code == 404
        vh = login(client, viewer.email, vpassword)
        assert client.get("/api/v1/clients", headers=vh).status_code == 200
        assert client.post("/api/v1/clients", json={"name": "x"}, headers=vh).status_code == 403
        assert client.get("/api/v1/documents", headers=vh).status_code == 403
    async with sessions() as session:
        lead = await session.get(Lead, lead_id)
    assert lead is not None
    assert (lead.stage, lead.client_id) == ("customer", client_id)


async def test_document_upload_extracts_text_and_download_is_logged(
    sessions: async_sessionmaker[AsyncSession], live_settings: Settings
) -> None:
    class Storage(MemoryStorage):
        async def presigned_get(self, bucket: str, key: str, expires_s: int = 600) -> str:
            return f"http://s3/{key}"

    manager, password = await make_user(sessions, "docs@railtech.uz", ["manager"])
    async with sessions() as session, session.begin():
        client = Client(name="Гамма")
        session.add(client)
        await session.flush()
        client_id = client.id
    app = create_app(live_settings)
    queued: list[int] = []
    with TestClient(app) as http:
        storage = Storage()

        async def enqueue(document_id: int) -> None:
            queued.append(document_id)

        service = DocumentService(sessions, storage, FakeConverter(), "client-documents", enqueue)
        app.state.container.__dict__["document_service"] = service
        headers = login(http, manager.email, password)
        created = http.post(
            "/api/v1/documents",
            headers=headers,
            data={
                "client_id": str(client_id),
                "type": "invoice",
                "title": "Счёт 77",
                "number": "77",
                "doc_date": "2026-07-20",
            },
            files={"file": ("schet.md", "Счёт на оплату трекеров".encode(), "text/markdown")},
        )
        assert created.status_code == 201, created.text
        document_id = created.json()["id"]
        assert queued == [document_id]
        assert await service.extract_text(document_id) == "done"
        download = http.get(f"/api/v1/documents/{document_id}/download", headers=headers)
        assert download.content == "Счёт на оплату трекеров".encode()
        access = http.get(f"/api/v1/documents/{document_id}/access", headers=headers).json()
        assert [a["accessed_by_type"] for a in access] == ["user"]
    async with sessions() as session:
        doc = await session.get(Document, document_id)
    assert doc is not None
    assert "трекеров" in (doc.extracted_text or "")


async def test_deactivated_client_gets_no_documents(
    service: tuple[ConversationService, ReplayModel, list[str]],
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    svc, model, _ = service
    client_id = await customer(sessions, svc)
    async with sessions() as session, session.begin():
        client = await session.get(Client, client_id)
        assert client is not None
        client.is_active = False
    model.responses.append(reply("Уточню у коллег."))
    out = await svc.handle_message(msg("Пришлите договор, который мы заключали в июле"))
    assert all(o.document is None for o in out)
    async with sessions() as session:
        assert (await session.scalars(select(DocumentAccessLog))).all() == []
