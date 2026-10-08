"""S3-хранилище файлов (RustFS, ADR-0009).

Приложение работает только по протоколу S3; конкретный сервер — деталь инфраструктуры.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
from aiobotocore.session import get_session
from pydantic import AnyHttpUrl

from app.config import Settings


async def ping(client: httpx.AsyncClient, endpoint: AnyHttpUrl) -> None:
    """Liveness RustFS (`GET /health`); не требует учётных данных."""
    response = await client.get(f"{str(endpoint).rstrip('/')}/health")
    response.raise_for_status()


class ObjectStorage:
    """Тонкая обёртка над aiobotocore: put/get/presign. Клиент создаётся на операцию."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._session = get_session()

    @asynccontextmanager
    async def _client(self) -> AsyncIterator[Any]:
        s = self._settings
        async with self._session.create_client(
            "s3",
            endpoint_url=str(s.s3_endpoint).rstrip("/"),
            aws_access_key_id=s.s3_access_key.get_secret_value(),
            aws_secret_access_key=s.s3_secret_key.get_secret_value(),
            region_name=s.s3_region,
        ) as client:
            yield client

    async def put(self, bucket: str, key: str, data: bytes, content_type: str) -> None:
        async with self._client() as client:
            await client.put_object(Bucket=bucket, Key=key, Body=data, ContentType=content_type)

    async def get(self, bucket: str, key: str) -> bytes:
        async with self._client() as client:
            response = await client.get_object(Bucket=bucket, Key=key)
            async with response["Body"] as stream:
                data: bytes = await stream.read()
                return data

    async def presigned_get(self, bucket: str, key: str, expires_s: int = 600) -> str:
        async with self._client() as client:
            url: str = await client.generate_presigned_url(
                "get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=expires_s
            )
            return url

    async def delete(self, bucket: str, key: str) -> None:
        async with self._client() as client:
            await client.delete_object(Bucket=bucket, Key=key)
