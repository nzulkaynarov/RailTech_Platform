"""LiteLLM Proxy — единственный шлюз к моделям (SPEC §1.6)."""

import httpx
from pydantic import AnyHttpUrl


async def ping(client: httpx.AsyncClient, base_url: AnyHttpUrl) -> None:
    """Liveness прокси. Доступность конкретных моделей здесь не проверяется."""
    response = await client.get(f"{str(base_url).rstrip('/')}/health/liveliness")
    response.raise_for_status()
