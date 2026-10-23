"""Документ товара — приватный (S0-9): лежит в `erp-private`, не открывается через /media, скачивается потоком.

Раньше файл лежал в публичном `erp-public` и отдавался по `/media/products/<id>/docs/...` без входа. Теперь —
`GET /api/v1/catalog/products/{id}/download-document/{doc_id}/` с теми же правами чтения, что у карточки товара.
"""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import Company, CompanyMember, CompanyRole, CompanyType, CustomUser, WorkspaceRole
from catalog.models import Product, ProductDocument, ProductStatus
from core import storage as storage_module

pytestmark = pytest.mark.django_db

PDF_BYTES = b"%PDF-1.4 passport " + b"\x00" * 64


def _client_for(user) -> APIClient:
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
    return client


@pytest.fixture
def world(db, settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    published, _ = ProductStatus.objects.get_or_create(
        code="PUBLISHED", defaults={"name": "Опубликован", "sort_order": 20}
    )
    supplier_type, _ = CompanyType.objects.get_or_create(
        code="SUPPLIER", defaults={"name": "Поставщик", "sort_order": 20}
    )
    workspace_role, _ = WorkspaceRole.objects.get_or_create(
        code="SALES_MANAGER", defaults={"name": "Менеджер", "sort_order": 20}
    )
    company = Company.objects.create(name="ООО Документы", inn="9800000001")
    company.types.add(supplier_type)
    role = CompanyRole.objects.create(company=company, name="Каталог", permissions=["catalog.manage"])
    user = CustomUser.objects.create_user(email="staff@docs.test", username="staff@docs.test", password="pw")
    CompanyMember.objects.create(
        user=user,
        company=company,
        role=workspace_role,
        company_roles=[role],
        is_active=True,
        is_primary=True,
        can_sell=True,
    )
    product = Product.objects.create(name="Колодка", owner_company=company, status=published)
    return {"user": user, "product": product, "company": company}


def _upload(world, name="Паспорт изделия", filename="passport.pdf"):
    response = _client_for(world["user"]).post(
        f"/api/v1/catalog/products/{world['product'].pk}/upload-document/",
        {"file": SimpleUploadedFile(filename, PDF_BYTES, content_type="application/pdf"), "name": name},
        format="multipart",
    )
    assert response.status_code == 201, response.content
    return response.json()


def test_document_field_uses_the_private_bucket():
    assert ProductDocument._meta.get_field("file")._storage_callable is storage_module.get_private_storage


def test_serializer_returns_the_download_path_not_a_media_url(world):
    payload = _upload(world)

    doc = world["product"].documents.get()
    assert payload["file"] == f"/api/v1/catalog/products/{world['product'].pk}/download-document/{doc.pk}/"
    assert "/media/" not in payload["file"]
    detail = _client_for(world["user"]).get(f"/api/v1/catalog/products/{world['product'].pk}/").json()
    assert detail["documents"][0]["file"] == payload["file"]


def test_document_without_a_file_has_null_file(world):
    doc = ProductDocument.objects.create(product=world["product"], name="Ссылка", file_url="https://example.org/d.pdf")

    payload = _client_for(world["user"]).get(f"/api/v1/catalog/products/{world['product'].pk}/").json()

    assert payload["documents"][0]["file"] is None
    assert payload["documents"][0]["file_url"] == "https://example.org/d.pdf"
    response = _client_for(world["user"]).get(
        f"/api/v1/catalog/products/{world['product'].pk}/download-document/{doc.pk}/"
    )
    assert response.status_code == 404 and response.json() == {"detail": "DOCUMENT_NOT_FOUND"}


def test_download_streams_the_file_with_headers(world):
    payload = _upload(world)

    response = _client_for(world["user"]).get(payload["file"])

    assert response.status_code == 200
    assert b"".join(response.streaming_content) == PDF_BYTES
    assert response["Content-Length"] == str(len(PDF_BYTES))
    assert response["Content-Disposition"].startswith("attachment; filename=")
    assert response["Content-Type"] == "application/pdf"
    assert response["X-Content-Type-Options"] == "nosniff"
    assert response["Cache-Control"] == "private, no-store"


def test_download_requires_login(world):
    payload = _upload(world)

    assert APIClient().get(payload["file"]).status_code == 401


def test_download_of_a_document_of_another_product_is_404(world):
    payload = _upload(world)
    other = Product.objects.create(name="Другой", owner_company=world["company"], status=world["product"].status)
    doc_id = world["product"].documents.get().pk

    response = _client_for(world["user"]).get(f"/api/v1/catalog/products/{other.pk}/download-document/{doc_id}/")

    assert response.status_code == 404 and payload["file"]


def test_unpublished_product_of_a_foreign_company_is_not_downloadable(world):
    """Видимость — как у карточки: чужой неопубликованный товар для обычного сотрудника не существует (404)."""
    foreign_company = Company.objects.create(name="Чужая", inn="9800000002")
    draft, _ = ProductStatus.objects.get_or_create(code="DRAFT", defaults={"name": "Черновик", "sort_order": 10})
    foreign = Product.objects.create(name="Секрет", owner_company=foreign_company, status=draft)
    doc = ProductDocument.objects.create(
        product=foreign, name="Закрытый", file=SimpleUploadedFile("s.pdf", PDF_BYTES, content_type="application/pdf")
    )

    response = _client_for(world["user"]).get(f"/api/v1/catalog/products/{foreign.pk}/download-document/{doc.pk}/")

    assert response.status_code == 404


def test_document_key_is_not_served_through_media(world):
    _upload(world)
    key = world["product"].documents.get().file.name

    assert key.startswith(f"products/{world['product'].pk}/docs/")
    assert APIClient().get(f"/media/{key}").status_code == 404
