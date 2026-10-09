"""kb-mcp: поиск по базе знаний для агентов (SPEC §7.1; ADR-0007).

Инструменты: `search_kb(query, product_key?, top_k?)`, `list_products()`.
Идентификаторы лида не принимаются аргументами — только из `X-Agent-Context`.
"""

from typing import Any, Final

from mcp.server.mcpserver import Context, MCPServer
from pydantic import BaseModel, Field

from app.container import Container, get_container
from app.mcp.common import build_app, require_context, serve
from app.repositories import kb as repo
from app.services.kb.search import DEFAULT_MIN_SCORE, KbSearchService

SERVICE: Final = "kb-mcp"
PORT: Final = 8101
MAX_TOP_K: Final = 10


class KbHit(BaseModel):
    chunk_id: int
    document_title: str
    product_key: str | None
    heading_path: str | None
    content: str
    similarity: float | None


class KbSearchResponse(BaseModel):
    hits: list[KbHit]
    best_score: float | None
    confident: bool = Field(description="best_score ≥ порога kb.min_score")
    language: str


class ProductInfo(BaseModel):
    key: str
    name: str
    description: str | None


def create_server(container: Container | None = None) -> MCPServer[Any]:
    c = container or get_container()
    server: MCPServer[Any] = MCPServer(
        "kb-mcp", instructions="Поиск по согласованной базе знаний компании RailTech."
    )
    search_service = KbSearchService(c.session_factory, c.embedder)

    @server.tool(description="Найти фрагменты базы знаний по вопросу клиента.")
    async def search_kb(
        query: str, ctx: Context[Any, Any], product_key: str | None = None, top_k: int = 6
    ) -> KbSearchResponse:
        agent = require_context(ctx, c.settings)
        result = await search_service.search(
            query[:2000],
            product_key=product_key,
            top_k=max(1, min(top_k, MAX_TOP_K)),
            language=agent.language,
        )
        hits = [
            KbHit(
                chunk_id=h.chunk_id,
                document_title=h.document_title,
                product_key=h.product_key,
                heading_path=h.heading_path,
                content=h.content,
                similarity=h.similarity,
            )
            for h in result.hits
        ]
        return KbSearchResponse(
            hits=hits,
            best_score=result.best_score,
            confident=result.is_confident(DEFAULT_MIN_SCORE),
            language=result.language,
        )

    @server.tool(description="Список активных продуктов компании.")
    async def list_products(ctx: Context[Any, Any]) -> list[ProductInfo]:
        require_context(ctx, c.settings)
        async with c.session_factory() as session:
            products = await repo.list_products(session)
        return [ProductInfo(key=p.key, name=p.name, description=p.description) for p in products]

    return server


def main() -> None:
    serve(build_app(create_server(), SERVICE, PORT), PORT)
