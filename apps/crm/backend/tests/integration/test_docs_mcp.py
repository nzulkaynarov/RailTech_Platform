"""Cross-tenant: документы клиента доступны боту только этого клиента (SPEC §11, DoD Фазы 6).

Обязательные негативные тесты: чужой document_id, режим prospect / без клиента,
поддельный и просроченный контекст. Плюс поиск по типу и дате.
"""

import base64
import json
from collections.abc import AsyncIterator
from datetime import date
from typing import Any

import httpx2
import pytest
from mcp import Client as McpClient
from mcp.client.streamable_http import streamable_http_client
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.container import Container
from app.mcp.common import build_app
from app.mcp.docs_server import create_server
from app.models.clients import Client, Document, DocumentAccessLog
from app.repositories import leads as leads_repo
from app.security.agent_context import HEADER_NAME, issue
from tests.integration.servers import free_port, running

pytestmark = pytest.mark.integration


class FakeStorage:
    async def presigned_get(self, bucket: str, key: str, expires_s: int = 600) -> str:
        return f"http://s3.local/{bucket}/{key}?ttl={expires_s}"


@pytest.fixture
async def world(sessions: async_sessionmaker[AsyncSession]) -> dict[str, int]:
    async with sessions() as session, session.begin():
        lead, _, _ = await leads_repo.create_lead_with_identity(
            session,
            tg_user_id=7777,
            username=None,
            first_name="A",
            chat_id=7777,
            language="ru",
            identity=None,
        )
        a, b = Client(name="Альфа"), Client(name="Бета")
        session.add_all([a, b])
        await session.flush()
        docs = [
            Document(
                client_id=a.id,
                type="contract",
                title="Договор поставки",
                number="15/2026",
                doc_date=date(2026, 7, 14),
                storage_key="k/a1",
                filename="a1.pdf",
                mime="application/pdf",
                size_bytes=1,
            ),
            Document(
                client_id=a.id,
                type="invoice",
                title="Счёт за июль",
                number="77",
                doc_date=date(2026, 7, 20),
                storage_key="k/a2",
                filename="a2.pdf",
                mime="application/pdf",
                size_bytes=1,
            ),
            Document(
                client_id=a.id,
                type="act",
                title="Скрытый акт",
                doc_date=date(2026, 7, 21),
                storage_key="k/a3",
                filename="a3.pdf",
                mime="application/pdf",
                size_bytes=1,
                is_visible_to_client=False,
            ),
            Document(
                client_id=b.id,
                type="contract",
                title="Договор Беты",
                doc_date=date(2026, 7, 10),
                storage_key="k/b1",
                filename="b1.pdf",
                mime="application/pdf",
                size_bytes=1,
            ),
        ]
        session.add_all(docs)
        await session.flush()
        return {
            "lead": lead.id,
            "a": a.id,
            "b": b.id,
            "a1": docs[0].id,
            "a3": docs[2].id,
            "b1": docs[3].id,
        }


@pytest.fixture
async def url(
    sessions: async_sessionmaker[AsyncSession], live_settings: Settings
) -> AsyncIterator[str]:
    container = Container(live_settings)
    container.__dict__["session_factory"] = sessions
    container.__dict__["storage"] = FakeStorage()
    port = free_port()
    async with running(build_app(create_server(container), "docs-mcp", port), port) as address:
        yield address


async def call(url: str, token: str | None, tool: str, args: dict[str, Any]) -> Any:
    headers = {HEADER_NAME: token} if token else {}
    async with (
        httpx2.AsyncClient(headers=headers) as http,
        McpClient(streamable_http_client(url, http_client=http)) as client,
    ):
        return await client.call_tool(tool, args)


def token(settings: Settings, world: dict[str, int], client: str = "a", **extra: Any) -> str:
    return issue(
        settings.agent_context_key_bytes,
        lead_id=world["lead"],
        mode="customer",
        language="ru",
        client_id=world[client],
        **extra,
    )


def payload(result: Any) -> Any:
    content = result.structured_content
    return (
        content["result"] if isinstance(content, dict) and set(content) == {"result"} else content
    )


async def test_search_returns_only_own_visible_documents(
    url: str, world: dict[str, int], live_settings: Settings
) -> None:
    result = await call(url, token(live_settings, world), "search_documents", {"query": "договор"})
    titles = {d["title"] for d in payload(result)}
    assert titles == {"Договор поставки", "Счёт за июль"}  # без скрытого и без чужого


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        ({"query": "x", "type": "contract"}, ["Договор поставки"]),
        ({"query": "x", "date_from": "2026-07-15", "date_to": "2026-08-01"}, ["Счёт за июль"]),
        ({"query": "x", "number": "15/2026"}, ["Договор поставки"]),
        (
            {"query": "x", "type": "contract", "date_from": "2026-01-01", "date_to": "2026-02-01"},
            [],
        ),
    ],
)
async def test_search_filters(
    url: str,
    world: dict[str, int],
    live_settings: Settings,
    args: dict[str, Any],
    expected: list[str],
) -> None:
    result = await call(url, token(live_settings, world), "search_documents", args)
    assert [d["title"] for d in payload(result)] == expected


async def test_link_for_own_document_is_logged(
    url: str,
    world: dict[str, int],
    live_settings: Settings,
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    result = await call(
        url, token(live_settings, world), "get_document_link", {"document_id": world["a1"]}
    )
    link = payload(result)
    assert link["url"].startswith("http://s3.local/client-documents/k/a1")
    assert link["expires_in_s"] == 600
    async with sessions() as session:
        entry = (await session.scalars(select(DocumentAccessLog))).one()
    assert (entry.document_id, entry.accessed_by_type, entry.tg_user_id) == (
        world["a1"],
        "bot",
        7777,
    )


@pytest.mark.parametrize("target", ["b1", "a3"], ids=["foreign-client", "hidden-from-client"])
async def test_cannot_get_foreign_or_hidden_document(
    url: str,
    world: dict[str, int],
    live_settings: Settings,
    target: str,
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    result = await call(
        url, token(live_settings, world), "get_document_link", {"document_id": world[target]}
    )
    assert result.is_error
    async with sessions() as session:
        assert (await session.scalars(select(DocumentAccessLog))).first() is None


async def test_prospect_context_is_rejected(
    url: str, world: dict[str, int], live_settings: Settings
) -> None:
    prospect = issue(
        live_settings.agent_context_key_bytes, lead_id=world["lead"], mode="prospect", language="ru"
    )
    for tool, args in (
        ("search_documents", {"query": "договор"}),
        ("get_document_link", {"document_id": world["a1"]}),
    ):
        assert (await call(url, prospect, tool, args)).is_error


@pytest.mark.parametrize("kind", ["missing", "forged", "foreign-key", "expired"])
async def test_invalid_context_is_rejected(
    url: str, world: dict[str, int], live_settings: Settings, kind: str
) -> None:
    good = token(live_settings, world)
    tokens = {
        "missing": None,
        "forged": good.split(".")[0] + ".AAAA",
        "foreign-key": issue(
            b"another-key-0123456789abcdef",
            lead_id=world["lead"],
            mode="customer",
            language="ru",
            client_id=world["a"],
        ),
        "expired": token(live_settings, world, ttl_s=-100),
    }
    result = await call(url, tokens[kind], "get_document_link", {"document_id": world["a1"]})
    assert result.is_error


async def test_tampered_client_id_is_rejected(
    url: str, world: dict[str, int], live_settings: Settings
) -> None:
    """Подмена client_id в теле контекста без ключа ломает подпись."""
    good = token(live_settings, world)
    body, signature = good.split(".")
    data = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    data["client_id"] = world["b"]
    forged = (
        base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode() + "." + signature
    )
    result = await call(url, forged, "get_document_link", {"document_id": world["b1"]})
    assert result.is_error
