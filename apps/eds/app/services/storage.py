"""Хранилище содержимого файлов: S3 (RustFS, бакет `eds-private`, ключ сервиса `S3_EDS_*`) и память для тестов.

Приложение работает только по протоколу S3 (ADR-0009). Ключ объекта — `files/<file_id>/v<версия>`: имён и данных
клиентов в ключах нет, версия объекта неизменяема. Чтение — потоком, чанками: файл целиком в память не грузится.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Protocol

from aiobotocore.session import get_session

from app.config import Settings

CHUNK = 64 * 1024


class ObjectStorage(Protocol):
    async def put(self, key: str, data: bytes, content_type: str) -> None: ...

    def stream(self, key: str) -> AsyncIterator[bytes]: ...

    async def presign(self, key: str, ttl_seconds: int) -> str:
        """Подписанная ссылка на чтение одного объекта со сроком — для вложения письма через почтовый сервис CRM
        (W18A-P1): ключи S3 у каждого сервиса свои, CRM получает только ссылку."""
        ...


class S3Storage:
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

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        async with self._client() as client:
            await client.put_object(Bucket=self._settings.s3_bucket, Key=key, Body=data, ContentType=content_type)

    async def presign(self, key: str, ttl_seconds: int) -> str:
        async with self._client() as client:
            url: str = await client.generate_presigned_url(
                "get_object", Params={"Bucket": self._settings.s3_bucket, "Key": key}, ExpiresIn=ttl_seconds
            )
            return url

    async def stream(self, key: str) -> AsyncIterator[bytes]:
        async with self._client() as client:
            response = await client.get_object(Bucket=self._settings.s3_bucket, Key=key)
            async with response["Body"] as body:
                async for chunk in body.iter_chunks(CHUNK):
                    yield chunk


class MemoryStorage:
    """Объекты в памяти процесса — для тестов (внешней сети нет); отдаёт содержимое теми же чанками, что S3."""

    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        self.objects[key] = (data, content_type)

    async def presign(self, key: str, ttl_seconds: int) -> str:
        return f"memory://eds-private/{key}?expires={ttl_seconds}"

    async def stream(self, key: str) -> AsyncIterator[bytes]:
        data, _ = self.objects[key]
        for start in range(0, len(data), CHUNK):
            yield data[start : start + CHUNK]


#: Одно хранилище на процесс тестов: приложение (контейнер на lifespan) и проверки теста видят одни и те же объекты.
TEST_STORAGE = MemoryStorage()


def build_storage(settings: Settings) -> ObjectStorage:
    return TEST_STORAGE if settings.app_env == "test" else S3Storage(settings)
