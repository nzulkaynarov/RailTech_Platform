"""docs-mcp: документы клиента для агента в режиме customer (SPEC §7.1, §11, сценарий C5).

`client_id` берётся только из подписанного контекста (`X-Agent-Context`) — модель
не может указать чужого клиента. Режим prospect и контекст без клиента — отказ.
"""

from datetime import date
from typing import Any, Final

from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel
from sqlalchemy import select

from app.container import Container, get_container
from app.mcp.common import build_app, require_context, serve
from app.models.leads import TelegramIdentity
from app.repositories import documents as repo
from app.security.agent_context import AgentContext
from app.services.documents import LINK_TTL_S, TYPES

SERVICE: Final = "docs-mcp"
PORT: Final = 8103


class DocumentHit(BaseModel):
    document_id: int
    title: str
    type: str
    number: str | None
    doc_date: date | None


class DocumentLink(BaseModel):
    document_id: int
    title: str
    filename: str
    mime: str
    url: str
    expires_in_s: int


def _customer(ctx: Context[Any, Any], c: Container) -> tuple[AgentContext, int]:
    agent = require_context(ctx, c.settings)
    if agent.mode != "customer" or agent.client_id is None:
        raise ToolError("documents are available only to a verified client")
    return agent, agent.client_id


def create_server(container: Container | None = None) -> MCPServer[Any]:
    c = container or get_container()
    server: MCPServer[Any] = MCPServer(SERVICE, instructions="Документы текущего клиента.")

    @server.tool(description="Найти документы текущего клиента (тип, период, номер, текст).")
    async def search_documents(
        query: str,
        ctx: Context[Any, Any],
        type: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        number: str | None = None,
    ) -> list[DocumentHit]:
        _, client_id = _customer(ctx, c)
        if type is not None and type not in TYPES:
            raise ToolError("unknown document type")
        flt = repo.DocumentFilter(type, date_from, date_to, number)
        async with c.session_factory() as session:
            rows = await repo.search_for_client(session, client_id, query[:500], flt)
        return [
            DocumentHit(
                document_id=r.id, title=r.title, type=r.type, number=r.number, doc_date=r.doc_date
            )
            for r in rows
        ]

    @server.tool(description="Ссылка на файл документа текущего клиента (10 минут).")
    async def get_document_link(document_id: int, ctx: Context[Any, Any]) -> DocumentLink:
        agent, client_id = _customer(ctx, c)
        async with c.session_factory() as session, session.begin():
            row = await repo.get_for_client(session, client_id, document_id)
            if row is None or row.storage_key is None:
                raise ToolError("document not found")
            tg_user_id = await session.scalar(
                select(TelegramIdentity.tg_user_id).where(TelegramIdentity.lead_id == agent.lead_id)
            )
            await repo.log_access(session, row.id, "bot", agent.lead_id, tg_user_id)
            key, title, filename, mime = row.storage_key, row.title, row.filename, row.mime
        url = await c.storage.presigned_get(c.settings.s3_bucket_documents, key, LINK_TTL_S)
        return DocumentLink(
            document_id=document_id,
            title=title,
            filename=filename,
            mime=mime,
            url=url,
            expires_in_s=LINK_TTL_S,
        )

    return server


def main() -> None:
    serve(build_app(create_server(), SERVICE, PORT), PORT)
