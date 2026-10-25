"""Подменённое хранилище S3 для тестов потоковой отдачи (S0-9, T3): объект «нужного размера» отдаётся лениво.

`FakeBody` ведёт себя как `StreamingBody` botocore, `FakeBucket` — как `bucket.Object(key).get()`, `s3_storage` оборачивает
настоящий `TrackedStorageMixin.open_stream` вокруг подменённого bucket. Память меряет `peak_memory_of` (`tracemalloc`) при
чтении ответа так, как это делает ASGI-обработчик Django (`async for` по ответу, `drain`).
"""

import asyncio
import tracemalloc
from contextlib import contextmanager
from unittest.mock import patch

from botocore.exceptions import ClientError

from core import storage as storage_module

MB = 1024 * 1024


@contextmanager
def s3_status_not_touched():
    """`external_call("s3")` пишет отметки в кэш и читает выключатель из БД — к потоковой отдаче это не относится."""
    with (
        patch("core.external_status.is_enabled", return_value=True),
        patch("core.external_status.record_success"),
        patch("core.external_status.record_failure"),
    ):
        yield


class FakeBody:
    """Как `botocore.response.StreamingBody`: порции по запросу, `close()` освобождает соединение."""

    def __init__(self, size):
        self._left = size
        self.closed = False
        self.produced = 0

    def iter_chunks(self, chunk_size):
        while self._left > 0:
            part = min(chunk_size, self._left)
            self._left -= part
            self.produced += part
            yield b"x" * part

    def close(self):
        self.closed = True


class FakeObject:
    def __init__(self, bucket, key):
        self._bucket, self._key = bucket, key

    def get(self):
        if self._key not in self._bucket.sizes:
            raise ClientError({"Error": {"Code": "NoSuchKey", "Message": "missing"}}, "GetObject")
        body = FakeBody(self._bucket.sizes[self._key])
        self._bucket.bodies.append(body)
        return {"Body": body, "ContentLength": self._bucket.sizes[self._key]}


class FakeBucket:
    def __init__(self, **sizes):
        self.sizes = sizes
        self.bodies = []

    def Object(self, key):  # noqa: N802 — имя метода boto3
        return FakeObject(self, key)


def s3_storage(bucket):
    """Настоящий `TrackedStorageMixin.open_stream` поверх подменённого bucket (S3Boto3Storage не создаётся)."""
    cls = type(
        "FakeS3",
        (storage_module.TrackedStorageMixin,),
        {"_normalize_name": lambda self, name: name, "bucket": bucket},
    )
    return cls()


async def drain(response):
    """Как ASGI-обработчик Django: читает ответ порциями и отбрасывает их. Возвращает число прочитанных байт."""
    total = 0
    async for chunk in response:
        total += len(chunk)
    return total


def peak_memory_of(coro_factory):
    tracemalloc.start()
    try:
        result = asyncio.run(coro_factory())
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    return result, peak
