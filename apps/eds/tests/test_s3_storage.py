"""S3Storage против локального S3-совместимого сервера в процессе теста (без сети): запись и потоковое чтение."""

from collections.abc import AsyncIterator

import pytest
from aiohttp import web
from pydantic import AnyHttpUrl, SecretStr

from app.config import Settings
from app.services.storage import CHUNK, S3Storage
from tests.conftest import ACCESS_SECRET


class FakeS3:
    """Минимальный S3: PUT и GET объекта (path-style), без проверки подписи."""

    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}
        self.requests: list[tuple[str, str, str | None]] = []

    async def put(self, request: web.Request) -> web.Response:
        key = request.match_info["key"]
        self.objects[f"{request.match_info['bucket']}/{key}"] = (
            await request.read(),
            request.headers.get("Content-Type", ""),
        )
        self.requests.append(("PUT", request.path, request.headers.get("Authorization")))
        return web.Response(headers={"ETag": '"fake"'})

    async def get(self, request: web.Request) -> web.StreamResponse:
        found = self.objects.get(f"{request.match_info['bucket']}/{request.match_info['key']}")
        self.requests.append(("GET", request.path, request.headers.get("Authorization")))
        if found is None:
            return web.Response(
                status=404, text="<Error><Code>NoSuchKey</Code></Error>", content_type="application/xml"
            )
        return web.Response(body=found[0], content_type=found[1])


@pytest.fixture
async def s3() -> AsyncIterator[tuple[FakeS3, S3Storage]]:
    fake = FakeS3()
    app = web.Application()
    app.router.add_put("/{bucket}/{key:.+}", fake.put)
    app.router.add_get("/{bucket}/{key:.+}", fake.get)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]  # type: ignore[union-attr]
    settings = Settings(
        EDS_DATABASE_URL="postgresql+psycopg://u:p@127.0.0.1:1/x",
        EDS_ACCESS_SECRET=ACCESS_SECRET,
        PLATFORM_SSO_SECRET="s" * 40,
        s3_endpoint=AnyHttpUrl(f"http://127.0.0.1:{port}"),
        s3_access_key=SecretStr("test-key"),
        s3_secret_key=SecretStr("test-secret"),
        s3_bucket="eds-private",
    )
    yield fake, S3Storage(settings)
    await runner.cleanup()


async def test_put_then_stream_in_chunks(s3: tuple[FakeS3, S3Storage]) -> None:
    fake, storage = s3
    data = bytes(range(256)) * ((CHUNK * 2 + 123) // 256 + 1)
    await storage.put("files/abc/v1", data, "application/pdf")
    assert fake.objects["eds-private/files/abc/v1"] == (data, "application/pdf")
    assert all(
        auth and auth.startswith("AWS4-HMAC-SHA256") for _, _, auth in fake.requests
    )  # запросы подписаны ключом сервиса

    chunks = [chunk async for chunk in storage.stream("files/abc/v1")]
    assert len(chunks) >= 3 and max(len(c) for c in chunks) <= CHUNK
    assert b"".join(chunks) == data


async def test_missing_object_raises(s3: tuple[FakeS3, S3Storage]) -> None:
    _, storage = s3
    with pytest.raises(Exception, match="NoSuchKey"):
        _ = [chunk async for chunk in storage.stream("files/none/v1")]
