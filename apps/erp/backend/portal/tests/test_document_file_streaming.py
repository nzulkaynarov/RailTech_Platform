"""PDF документа клиенту отдаётся потоком порциями (S0-9, хвост T3).

Раньше портал (и публичный маршрут ссылки CRM — тест в `integration/tests/test_documents_link.py`) делал `FileResponse(document.file.open("rb"))`: `S3Boto3StorageFile` при первом `read()` скачивает
объект целиком, поэтому файл в десятки МБ жил в памяти процесса. Теперь тело идёт через `core.file_streaming`. Тесты
подменяют хранилище поля `Invoice.pdf_file` на S3 с ленивым телом нужного размера (без реального S3) и проверяют, что
ответ — `ObjectStreamResponse`, заголовки прежние, а пик памяти при чтении ответа (`async for`, как в ASGI) не растёт
пропорционально размеру файла.
"""

from __future__ import annotations

import pytest
from portal.tests.test_portal_documents import API

from core.file_streaming import ObjectStreamResponse
from core.storage import STREAM_CHUNK_SIZE
from core.tests.s3_fakes import MB, FakeBucket, drain, peak_memory_of, s3_status_not_touched, s3_storage
from crm.models import Invoice

pytestmark = pytest.mark.django_db

BIG = 40 * MB


@pytest.fixture(autouse=True)
def _s3_status_not_touched():
    with s3_status_not_touched():
        yield


@pytest.fixture
def s3_invoice(contract_world, monkeypatch):
    """Готовый счёт, чей PDF лежит в «S3» размером `BIG`; возвращает (id документа портала, имя объекта, bucket)."""
    document_id = contract_world["ready_documents"]["invoice_paid"]
    from portal.services import documents as service

    # Имя объекта берём у настоящего поля, хранилище подменяем только у поля счёта.
    found = service.find_client_document(contract_world["company"], document_id)
    name = found.file.name
    bucket = FakeBucket(**{name: BIG})
    monkeypatch.setattr(Invoice._meta.get_field("pdf_file"), "storage", s3_storage(bucket))
    return document_id, name, bucket


def test_portal_file_is_streamed_in_chunks(portal_client, s3_invoice):
    document_id, name, bucket = s3_invoice

    response = portal_client.get(f"{API}/documents/{document_id}/file")

    assert response.status_code == 200
    assert isinstance(response, ObjectStreamResponse)
    assert response["Content-Type"] == "application/pdf"
    assert response["Content-Length"] == str(BIG)
    assert response["Content-Disposition"].startswith("attachment; filename")
    total, peak = peak_memory_of(lambda: drain(response))
    assert total == BIG
    assert peak < 4 * MB, f"пик памяти {peak / MB:.1f} МБ при файле {BIG / MB:.0f} МБ"
    assert bucket.bodies[0].produced == BIG
    assert bucket.bodies[0].closed, "после отдачи соединение с хранилищем закрыто"


def test_portal_file_closes_the_object_when_the_client_leaves(portal_client, s3_invoice):
    document_id, _, bucket = s3_invoice

    response = portal_client.get(f"{API}/documents/{document_id}/file")
    response.close()  # клиент оборвал соединение, ничего не прочитав

    assert bucket.bodies[0].closed
    assert bucket.bodies[0].produced <= STREAM_CHUNK_SIZE


def test_portal_file_missing_in_s3_is_pending_again(portal_client, contract_world, monkeypatch):
    """Объекта нет в S3 (имя в базе осталось): как и раньше — 202 и рендер в очередь, а не 500."""
    document_id = contract_world["ready_documents"]["invoice_paid"]
    monkeypatch.setattr(Invoice._meta.get_field("pdf_file"), "storage", s3_storage(FakeBucket()))
    queued = []
    monkeypatch.setattr("crm.tasks.render_document_pdf.delay", lambda doc_type, pk: queued.append((doc_type, pk)))
    from django.core.cache import cache

    cache.clear()

    response = portal_client.get(f"{API}/documents/{document_id}/file")

    assert response.status_code == 202 and "Retry-After" in response
    assert len(queued) == 1
