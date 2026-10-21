"""Сервисный режим (M3-CRM-07): клиент и компания ERP берутся из БД, а не от модели.

Настоящие crm/kb/docs-mcp и БД; erp-mcp — настоящий SDK-клиент поверх подставного транспорта
(`tests/unit/agents/fake_erp_mcp.py`), модель — записанные ответы. Платных вызовов нет.
"""

import base64
import json
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack
from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import AnyHttpUrl
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.dialog.graph import DialogAgent
from app.agents.erp_mcp import ErpMcpClient
from app.agents.llm import ToolCall
from app.agents.mcp_client import McpToolClient
from app.config import Settings
from app.container import Container
from app.mcp import crm_server, docs_server, kb_server
from app.mcp.common import build_app
from app.models.clients import Client, ServiceRequest
from app.models.leads import Lead, TelegramIdentity
from app.services.conversation import ConversationService, Incoming
from app.services.settings import SettingsService
from tests.fakes import FakeEmbedder
from tests.integration.servers import free_port, running
from tests.integration.test_docs_mcp import FakeStorage
from tests.unit.agents.fake_erp_mcp import FakeErpMcp, rejection, tool_ok
from tests.unit.agents.fakes import ReplayModel, reply

pytestmark = pytest.mark.integration
USER = 8810
ERP_KEY = b"integration-key-not-a-secret-0123456789"
DELIVERY = [
    {"erp_deal_id": 5, "line_no": 1, "title": "Трекер", "status": "shipped", "eta": "2026-10-25"}
]


class Sleeper:
    async def __call__(self, seconds: float) -> None:
        return None


@pytest.fixture
async def stand(
    sessions: async_sessionmaker[AsyncSession], live_settings: Settings
) -> AsyncIterator[tuple[ConversationService, ReplayModel, FakeErpMcp]]:
    container = Container(live_settings)
    container.__dict__["session_factory"] = sessions
    container.__dict__["embedder"] = FakeEmbedder()
    container.__dict__["storage"] = FakeStorage()
    fake = FakeErpMcp(lambda name, args: tool_ok(DELIVERY))
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
        erp = ErpMcpClient(
            "http://erp-mcp:8104/mcp/erp", ERP_KEY, transport=fake.transport, sleep=Sleeper()
        )
        svc = ConversationService(
            sessions,
            SettingsService(sessions, ttl_s=0),
            DialogAgent(McpToolClient(config), model, erp=erp),
            config.agent_context_key_bytes,
        )
        yield svc, model, fake


async def customer(
    sessions: async_sessionmaker[AsyncSession],
    svc: ConversationService,
    *,
    erp_company_id: int | None,
) -> int:
    await svc.start(Incoming(tg_user_id=USER, chat_id=USER, text="/start", language_code="ru"))
    await svc.accept_consent(USER)
    async with sessions() as session, session.begin():
        client = Client(name="Альфа", erp_company_id=erp_company_id)
        session.add(client)
        await session.flush()
        identity = (await session.scalars(select(TelegramIdentity))).one()
        identity.client_id, identity.verified_at = client.id, datetime.now(UTC)
        lead = await session.get(Lead, identity.lead_id)
        assert lead is not None
        lead.stage, lead.client_id = "customer", client.id
        return client.id


def msg(text: str) -> Incoming:
    return Incoming(tg_user_id=USER, chat_id=USER, text=text)


def claims(token: str) -> dict[str, Any]:
    payload = token.partition(".")[0]
    decoded: dict[str, Any] = json.loads(
        base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
    )
    return decoded


def tool_context(fake: FakeErpMcp) -> dict[str, Any]:
    pairs = zip(fake.contexts, fake.methods, strict=True)
    return claims(next(c for c, m in pairs if m == "tools/call"))


async def test_erp_context_comes_from_the_database(
    stand: tuple[ConversationService, ReplayModel, FakeErpMcp],
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    svc, model, fake = stand
    client_id = await customer(sessions, svc, erp_company_id=4242)
    forged = ToolCall(
        id="d1", name="get_delivery_status", arguments={"erp_deal_id": 5, "erp_company_id": 1}
    )
    model.responses += [reply("", forged), reply("Поставка ожидается 25 октября 2026 года.")]
    out = await svc.handle_message(msg("Когда поставка?"))
    assert out[-1].text == "Поставка ожидается 25 октября 2026 года."
    assert fake.tool_calls == [("get_delivery_status", {"erp_deal_id": 5})]
    seen = tool_context(fake)
    assert (seen["crm_client_id"], seen["erp_company_id"], seen["mode"]) == (
        client_id,
        4242,
        "customer",
    )


async def test_client_not_in_erp_gets_no_erp_calls(
    stand: tuple[ConversationService, ReplayModel, FakeErpMcp],
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    svc, model, fake = stand
    await customer(sessions, svc, erp_company_id=None)
    call = ToolCall(id="d1", name="get_delivery_status", arguments={"erp_deal_id": 5})
    model.responses += [reply("", call), reply("Передам менеджеру.")]
    await svc.handle_message(msg("Когда поставка?"))
    assert fake.methods == []  # ни одного запроса к erp-mcp


async def test_erp_down_creates_a_service_request_for_the_manager(
    stand: tuple[ConversationService, ReplayModel, FakeErpMcp],
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    svc, model, fake = stand
    client_id = await customer(sessions, svc, erp_company_id=4242)
    fake.reject_always(rejection(503, "down"), on="tools/call")
    call = ToolCall(id="d1", name="get_delivery_status", arguments={"erp_deal_id": 5})
    model.responses += [reply("", call), reply("Сейчас не могу это проверить.")]
    out = await svc.handle_message(msg("Когда поставка?"))
    async with sessions() as session:
        request = (await session.scalars(select(ServiceRequest))).one()
    assert request.client_id == client_id
    assert "Когда поставка?" in request.summary
    assert out[-1].text.startswith("Сейчас не могу это проверить.")
    assert f"№{request.id}" in out[-1].text


async def test_erp_down_twice_a_day_makes_one_request(
    stand: tuple[ConversationService, ReplayModel, FakeErpMcp],
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    svc, model, fake = stand
    await customer(sessions, svc, erp_company_id=4242)
    fake.reject_always(rejection(503, "down"), on="tools/call")
    call = ToolCall(id="d1", name="get_delivery_status", arguments={"erp_deal_id": 5})
    for _ in range(2):
        model.responses += [reply("", call), reply("Сейчас не могу это проверить.")]
        out = await svc.handle_message(msg("Когда поставка?"))
    async with sessions() as session:
        request = (await session.scalars(select(ServiceRequest))).one()
    assert f"№{request.id}" in out[-1].text  # повтор получил номер прежнего запроса


async def test_erp_answers_are_not_shown_to_a_deactivated_client(
    stand: tuple[ConversationService, ReplayModel, FakeErpMcp],
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    svc, model, _ = stand
    client_id = await customer(sessions, svc, erp_company_id=4242)
    call = ToolCall(id="d1", name="get_delivery_status", arguments={"erp_deal_id": 5})
    model.responses += [reply("", call), reply("Поставка ожидается 25 октября 2026 года.")]
    await svc.handle_message(msg("Когда поставка?"))
    async with sessions() as session, session.begin():
        client = await session.get(Client, client_id)
        assert client is not None
        client.is_active = False  # теперь с ним говорят как с лидом
    model.responses.append(reply("Подскажу по продуктам."))
    await svc.handle_message(msg("Что у вас есть?"))
    system = model.requests[-1][0]["content"]
    assert "25 октября" not in system
