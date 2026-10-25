"""Отдача файлов S3 порциями (S0-9): тело объекта не загружается целиком ни в память, ни на диск.

Хранилище подменено: `FakeBody` отдаёт «объект» нужного размера лениво (как `StreamingBody` botocore), `FakeBucket` ведёт
себя как `bucket.Object(key).get()`. Память меряет `tracemalloc` при чтении ответа так, как это делает ASGI-обработчик
Django (`async for` по ответу). Контроль чувствительности замера — тот же размер, собранный в список, как делал бы
синхронный итератор под ASGI: пик не меньше размера файла.
"""

import asyncio
import tracemalloc
from unittest.mock import patch

import pytest
from botocore.exceptions import ClientError
from django.http import Http404

from core import file_streaming
from core.storage import STREAM_CHUNK_SIZE, ObjectStream
from core.tests.s3_fakes import MB, FakeBody, FakeBucket, drain, peak_memory_of, s3_status_not_touched, s3_storage

BIG = 40 * MB  # «20–50 МБ» из задачи


@pytest.fixture(autouse=True)
def _s3_status_not_touched():
    with s3_status_not_touched():
        yield


def test_big_file_is_streamed_without_growing_memory():
    bucket = FakeBucket(**{"deals/1/quotes/big.pdf": BIG})
    storage = s3_storage(bucket)

    response = file_streaming.storage_file_response(
        storage, "deals/1/quotes/big.pdf", content_type="application/pdf", as_attachment=True, filename="big.pdf"
    )
    total, peak = peak_memory_of(lambda: drain(response))

    assert total == BIG
    # Порция — 256 КиБ; пик — порции в полёте и служебные объекты, а не 40 МБ.
    assert peak < 4 * MB, f"пик памяти {peak / MB:.1f} МБ при файле {BIG / MB:.0f} МБ"
    assert response["Content-Length"] == str(BIG)
    assert response["Content-Disposition"] == 'attachment; filename="big.pdf"'
    assert response["Content-Type"] == "application/pdf"


def test_memory_probe_is_sensitive_to_a_full_download():
    """Контроль: если собрать то же тело целиком (как синхронный итератор под ASGI), пик не меньше размера файла."""
    body = FakeBody(BIG)

    def whole():
        return list(body.iter_chunks(STREAM_CHUNK_SIZE))

    tracemalloc.start()
    try:
        chunks = whole()
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert sum(map(len, chunks)) == BIG
    assert peak >= BIG


def test_body_is_read_incrementally():
    """Клиент прочитал три порции — из хранилища прочитано три порции (плюс запас итератора), а не весь объект."""
    bucket = FakeBucket(**{"products/1/images/a.png": 10 * MB})
    stream = s3_storage(bucket).open_stream("products/1/images/a.png")

    async def three_chunks():
        got = 0
        async for chunk in stream.aiter_chunks():
            got += 1
            if got == 3:
                return

    asyncio.run(three_chunks())

    assert bucket.bodies[0].produced <= 4 * STREAM_CHUNK_SIZE
    assert bucket.bodies[0].closed, "обрыв чтения должен освободить соединение с хранилищем"


@pytest.mark.django_db  # `response.close()` отправляет request_finished — обработчик закрывает устаревшие соединения с БД
def test_full_read_and_close_release_the_connection():
    bucket = FakeBucket(**{"k.bin": 3 * STREAM_CHUNK_SIZE + 5})
    response = file_streaming.storage_file_response(
        s3_storage(bucket), "k.bin", content_type="application/octet-stream"
    )

    assert asyncio.run(drain(response)) == 3 * STREAM_CHUNK_SIZE + 5
    assert bucket.bodies[0].closed
    assert "Content-Disposition" not in response

    # Закрытие ответа без чтения (клиент ушёл) тоже закрывает тело.
    unread = file_streaming.storage_file_response(s3_storage(bucket), "k.bin", content_type="application/octet-stream")
    unread.close()
    assert bucket.bodies[1].closed


def test_sync_consumption_still_works_for_tests_and_wsgi():
    """Под WSGI/тестовым клиентом ответ читается синхронно (Django склеивает асинхронный итератор) — байты те же."""
    bucket = FakeBucket(**{"k.bin": 2 * STREAM_CHUNK_SIZE + 7})
    response = file_streaming.storage_file_response(
        s3_storage(bucket), "k.bin", content_type="application/octet-stream"
    )

    assert len(b"".join(response)) == 2 * STREAM_CHUNK_SIZE + 7


def test_missing_object_is_file_not_found_and_404():
    storage = s3_storage(FakeBucket())

    with pytest.raises(FileNotFoundError):
        storage.open_stream("nope.png")
    with patch("core.file_streaming.get_public_storage", return_value=storage):
        with pytest.raises(Http404):
            file_streaming.serve_public_media(None, "products/1/images/nope.png")
    with pytest.raises(Http404):
        file_streaming.stream_file_field(FieldFileLike(storage, "deals/1/quotes/nope.pdf"))


class FieldFileLike:
    """FieldFile-подобный объект: `storage`, `name`, истинное значение."""

    def __init__(self, storage, name):
        self.storage, self.name = storage, name

    def __bool__(self):
        return True


def test_other_storage_errors_are_not_swallowed():
    class Denied(FakeBucket):
        def Object(self, key):  # noqa: N802
            raise ClientError({"Error": {"Code": "AccessDenied", "Message": "no"}}, "GetObject")

    with pytest.raises(ClientError):
        s3_storage(Denied()).open_stream("k.bin")


def test_serve_public_media_keeps_its_headers_on_the_stream():
    bucket = FakeBucket(**{"companies/3/doc-profile/logo/a1.png": 1234})
    with patch("core.file_streaming.get_public_storage", return_value=s3_storage(bucket)):
        response = file_streaming.serve_public_media(None, "companies/3/doc-profile/logo/a1.png")

    assert response["Content-Length"] == "1234"
    assert response["Content-Type"] == "image/png"
    assert response["Cache-Control"] == "public, max-age=86400"
    assert response["X-Content-Type-Options"] == "nosniff"
    assert "sandbox" in response["Content-Security-Policy"]
    assert asyncio.run(drain(response)) == 1234


def test_stream_file_field_sets_attachment_with_the_file_name():
    bucket = FakeBucket(**{"deals/9/quotes/КП-1.pdf": 100})
    field = FieldFileLike(s3_storage(bucket), "deals/9/quotes/КП-1.pdf")

    response = file_streaming.stream_file_field(field)

    assert response["Content-Length"] == "100"
    assert response["Content-Disposition"].startswith("attachment; filename*=utf-8''")
    assert response["Content-Type"] == "application/pdf"


def test_object_stream_wraps_a_body():
    body = FakeBody(10)
    stream = ObjectStream(body, 10, "k")

    assert b"".join(stream.iter_chunks(4)) == b"x" * 10
    stream.close()
    assert body.closed
