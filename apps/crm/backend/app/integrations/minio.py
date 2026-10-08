"""MinIO (S3-совместимое хранилище файлов)."""

import httpx
from pydantic import AnyHttpUrl


async def ping(client: httpx.AsyncClient, endpoint: AnyHttpUrl) -> None:
    """Liveness MinIO; не требует учётных данных."""
    response = await client.get(f"{str(endpoint).rstrip('/')}/minio/health/live")
    response.raise_for_status()
