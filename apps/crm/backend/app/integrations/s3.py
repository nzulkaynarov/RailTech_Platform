"""S3-хранилище файлов (RustFS, ADR-0009).

Приложение работает только по протоколу S3; конкретный сервер — деталь инфраструктуры.
"""

import httpx
from pydantic import AnyHttpUrl


async def ping(client: httpx.AsyncClient, endpoint: AnyHttpUrl) -> None:
    """Liveness RustFS (`GET /health`); не требует учётных данных."""
    response = await client.get(f"{str(endpoint).rstrip('/')}/health")
    response.raise_for_status()
