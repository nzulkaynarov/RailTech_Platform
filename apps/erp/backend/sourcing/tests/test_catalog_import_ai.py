"""R5b — массовая загрузка каталога ЛЮБЫМ файлом через ИИ (import-catalog-ai).

Клиент Claude ВСЕГДА застаблен (ни одного платного/недетерминированного вызова). Проверяем
детерминированный контракт: бесплатный xlsx-путь не трогает ИИ и даёт отчёт, идентичный
штатному импорту; ИИ-путь прогоняет строки модели через ШТАТНОЕ ядро; staging-файл удаляется
после задачи при любом исходе; вьюха повторяет продавцовую авторизацию CatalogImportView.
"""

from io import BytesIO
from types import SimpleNamespace
from uuid import uuid4

import pandas as pd
import pytest
from ai.testing import install_fake_gateway
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from sourcing.catalog_import import run_catalog_import
from sourcing.tasks_ai import run_ai_job
from sourcing.views_imports import CATALOG_TEMPLATE_HEADERS

PDF_BYTES = b"%PDF-1.4 stub price list"


def _xlsx(records):
    buffer = BytesIO()
    pd.DataFrame(records).to_excel(buffer, index=False)
    return buffer.getvalue()


def _template_row(**overrides):
    """Строка со ВСЕМИ ключами схемы шаблона ('' по умолчанию) — как возвращает модель."""
    row = {header: "" for header in CATALOG_TEMPLATE_HEADERS}
    row.update(overrides)
    return row


def _stage(content: bytes, extension: str) -> str:
    return default_storage.save(f"ai_extract_tmp/{uuid4().hex}.{extension}", ContentFile(content))


def _stub_ai_client(monkeypatch, rows):
    """Фейковый шлюз LiteLLM отвечает строками прайса `rows`."""
    install_fake_gateway(monkeypatch).reply_json({"rows": rows})


def _forbid_ai_client(monkeypatch):
    """Бесплатный путь не должен дойти до шлюза: фейк без заготовок упадёт на любом вызове."""
    install_fake_gateway(monkeypatch)


@pytest.fixture
def lookups(db):
    from catalog.models import ProductStatus, StockStatus
    from master_data.models import Currency, UnitOfMeasure

    Currency.objects.get_or_create(code="UZS", defaults={"name": "Сум", "symbol": "сўм"})
    StockStatus.objects.get_or_create(code="IN_STOCK", defaults={"name": "В наличии"})
    ProductStatus.objects.get_or_create(code="DRAFT", defaults={"name": "Черновик"})
    UnitOfMeasure.objects.get_or_create(code="PCS", defaults={"name": "шт"})


@pytest.fixture
def seller_user(db):
    """Сотрудник своей компании с правом роли `catalog.manage` — та же авторизация, что у штатного
    import-catalog (M1-ERP-05)."""
    from accounts.models import Company, CompanyMember, CompanyRole, CompanyType, CustomUser, WorkspaceRole

    supplier_type = CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier"})[0]
    owner_role = WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner"})[0]
    company = Company.objects.create(name="AI Import Seller", inn="510000001")
    company.types.add(supplier_type)
    user = CustomUser.objects.create_user(
        email="ai-import-seller@x.test", username="ai-import-seller@x.test", password="pw", is_active=True
    )
    role = CompanyRole.objects.create(company=company, name="Каталог", permissions=["catalog.manage"])
    CompanyMember.objects.create(
        user=user, company=company, role=owner_role, is_active=True, can_sell=True, company_roles=[role]
    )
    return user, company


# ── Обработчик фичи: бесплатный xlsx-путь ───────────────────────────────────


@pytest.mark.django_db
def test_template_xlsx_free_path_no_ai_and_identical_report(lookups, company_factory, monkeypatch):
    """Наш шаблон → строки идут мимо ИИ (стаб падает при вызове), отчёт == штатному импорту."""
    _forbid_ai_client(monkeypatch)
    supplier = company_factory(name="FreePath", inn="111111111")
    content = _xlsx(
        [
            {
                "Наименование": "Тормозная колодка",
                "Бренд": "Knorr-Bremse",
                "Артикул производителя": "KB-100",
                "Цена": "150.50",
                "Валюта": "UZS",
                "Наличие": "IN_STOCK",
                "Мин. заказ": "5",
            }
        ]
    )
    standard = run_catalog_import(content, supplier_company_id=supplier.id, dry_run=True)

    storage_path = _stage(content, "xlsx")
    result = run_ai_job(
        "catalog_import_ai",
        {"storage_path": storage_path, "filename": "price.xlsx", "supplier_company_id": supplier.id, "dry_run": True},
    )

    assert result["ai_used"] is False
    assert result["ai_rows"] == 1
    ai_report = {key: value for key, value in result.items() if key not in ("ai_used", "ai_rows")}
    assert ai_report == standard
    assert not default_storage.exists(storage_path)  # staging удалён после задачи


@pytest.mark.django_db
def test_template_xlsx_free_path_persists_product_and_offer(lookups, company_factory, monkeypatch):
    _forbid_ai_client(monkeypatch)
    supplier = company_factory(name="FreePersist", inn="222222222")
    content = _xlsx(
        [{"Наименование": "Реле", "Бренд": "Siemens", "Артикул производителя": "S-9", "Цена": "10", "Валюта": "UZS"}]
    )

    storage_path = _stage(content, "xlsx")
    result = run_ai_job(
        "catalog_import_ai",
        {"storage_path": storage_path, "filename": "our.xlsx", "supplier_company_id": supplier.id, "dry_run": False},
    )

    assert result["status"] == "success"
    assert result["created"] == 1
    assert result["offers_upserted"] == 1

    from catalog.models import Product, SupplierOffer

    product = Product.objects.get(manufacturer_part_number="S-9")
    assert product.owner_company_id == supplier.id
    assert SupplierOffer.objects.filter(product=product, supplier=supplier).count() == 1


# ── Обработчик фичи: ИИ-путь (PDF со стабом) ────────────────────────────────


@pytest.mark.django_db
def test_pdf_ai_rows_go_through_the_standard_engine(lookups, company_factory, settings, monkeypatch):
    settings.AI_IMPORT_ENABLED = True
    supplier = company_factory(name="AiPath", inn="333333333")
    _stub_ai_client(
        monkeypatch,
        [
            _template_row(
                **{
                    "Наименование": "Автосцепка СА-3",
                    "Бренд": "УВЗ",
                    "Артикул производителя": "SA-3",
                    "Цена": "1200000.00",
                    "Валюта": "UZS",
                    "Наличие": "IN_STOCK",
                }
            )
        ],
    )

    storage_path = _stage(PDF_BYTES, "pdf")
    result = run_ai_job(
        "catalog_import_ai",
        {"storage_path": storage_path, "filename": "price.pdf", "supplier_company_id": supplier.id, "dry_run": False},
    )

    assert result["status"] == "success"
    assert result["ai_used"] is True
    assert result["ai_rows"] == 1
    assert result["created"] == 1
    assert result["offers_upserted"] == 1
    # Карточка без категории/ТН ВЭД порог публикации не проходит — отчёт честно это считает.
    assert result["unpublishable"] == 1
    assert not default_storage.exists(storage_path)

    from catalog.models import Product

    assert Product.objects.filter(manufacturer_part_number="SA-3").exists()


@pytest.mark.django_db
def test_ai_dry_run_persists_nothing(lookups, company_factory, settings, monkeypatch):
    settings.AI_IMPORT_ENABLED = True
    supplier = company_factory(name="AiDry", inn="444444444")
    _stub_ai_client(
        monkeypatch,
        [_template_row(**{"Наименование": "Колодка", "Бренд": "B", "Артикул производителя": "D-1", "Цена": "5"})],
    )

    storage_path = _stage(PDF_BYTES, "pdf")
    result = run_ai_job(
        "catalog_import_ai",
        {"storage_path": storage_path, "filename": "dry.pdf", "supplier_company_id": supplier.id, "dry_run": True},
    )

    assert result["dry_run"] is True
    assert result["created"] == 1

    from catalog.models import Manufacturer, Product, SupplierOffer

    assert Product.objects.count() == 0
    assert SupplierOffer.objects.count() == 0
    assert Manufacturer.objects.count() == 0


@pytest.mark.django_db
def test_empty_ai_answer_is_an_error_and_staging_is_deleted(lookups, settings, monkeypatch):
    settings.AI_IMPORT_ENABLED = True
    _stub_ai_client(monkeypatch, [])

    storage_path = _stage(PDF_BYTES, "pdf")
    result = run_ai_job("catalog_import_ai", {"storage_path": storage_path, "filename": "empty.pdf"})

    assert result == {"status": "error", "message": "AI_EXTRACT_EMPTY"}
    assert not default_storage.exists(storage_path)


@pytest.mark.django_db
def test_extract_failure_is_an_error_and_staging_is_deleted(lookups, settings, monkeypatch):
    """AI выключился между постановкой и запуском → стабильный код, файл всё равно удалён."""
    settings.AI_IMPORT_ENABLED = False

    storage_path = _stage(PDF_BYTES, "pdf")
    result = run_ai_job("catalog_import_ai", {"storage_path": storage_path, "filename": "off.pdf"})

    assert result == {"status": "error", "message": "AI_EXTRACT_FAILED"}
    assert not default_storage.exists(storage_path)


# ── Вьюха import-catalog-ai ─────────────────────────────────────────────────


@pytest.mark.django_db
def test_view_ai_disabled_returns_503(settings, seller_user):
    settings.AI_IMPORT_ENABLED = False
    user, _company = seller_user
    client = APIClient()
    client.force_authenticate(user)

    upload = SimpleUploadedFile("price.pdf", PDF_BYTES, content_type="application/pdf")
    response = client.post("/api/v1/sourcing/import-catalog-ai/", {"file": upload}, format="multipart")

    assert response.status_code == 503
    assert response.json()["detail"] == "AI_DISABLED"


@pytest.mark.django_db
def test_view_requires_seller_membership(settings, user_factory):
    settings.AI_IMPORT_ENABLED = True
    client = APIClient()
    client.force_authenticate(user_factory(email="not-seller@x.test", username="not-seller@x.test"))

    upload = SimpleUploadedFile("price.pdf", PDF_BYTES, content_type="application/pdf")
    response = client.post("/api/v1/sourcing/import-catalog-ai/", {"file": upload}, format="multipart")

    assert response.status_code == 403
    # M1-ERP-05: не сотрудник своей компании — отказ гейта ролей до вьюхи.
    assert response.json()["detail"] == "ROLE_NOT_PERMITTED"


@pytest.mark.django_db
def test_view_rejects_unsupported_extension_and_spoofed_magic(settings, seller_user):
    settings.AI_IMPORT_ENABLED = True
    user, _company = seller_user
    client = APIClient()
    client.force_authenticate(user)
    url = "/api/v1/sourcing/import-catalog-ai/"

    # Расширение вне allowlist (csv у AI-каталожного пути не принимается) → честный код.
    csv_upload = SimpleUploadedFile("price.csv", b"a;b;c", content_type="text/csv")
    response = client.post(url, {"file": csv_upload}, format="multipart")
    assert response.status_code == 400
    assert response.json()["detail"] == "FILE_TYPE_UNSUPPORTED"

    # Подделка: имя .xlsx, содержимое PDF → магия не сходится с расширением.
    spoofed = SimpleUploadedFile("price.xlsx", PDF_BYTES, content_type="application/vnd.ms-excel")
    response = client.post(url, {"file": spoofed}, format="multipart")
    assert response.status_code == 400
    assert response.json()["detail"] == "FILE_CONTENT_MISMATCH"


@pytest.mark.django_db
def test_view_enqueues_202_with_staged_file(settings, seller_user, monkeypatch):
    """202 {task_id} + AIJob-строка владельца; байты staged в default_storage, в payload —
    только ключ (через брокер байты не едут), плюс разрешённая компания продавца и dry_run."""
    settings.AI_IMPORT_ENABLED = True
    user, company = seller_user
    client = APIClient()
    client.force_authenticate(user)

    captured = {}

    def _apply_async(args=None, task_id=None, **kwargs):
        captured.update(feature=args[0], payload=args[1], task_id=task_id)
        return SimpleNamespace(id=task_id)

    monkeypatch.setattr("sourcing.tasks_ai.run_ai_job.apply_async", _apply_async)

    upload = SimpleUploadedFile("прайс.pdf", PDF_BYTES, content_type="application/pdf")
    response = client.post(
        "/api/v1/sourcing/import-catalog-ai/", {"file": upload, "dry_run": "true"}, format="multipart"
    )

    assert response.status_code == 202
    task_id = response.json()["task_id"]
    assert captured["task_id"] == task_id
    assert captured["feature"] == "catalog_import_ai"

    from sourcing.models import AIJob

    assert AIJob.objects.filter(celery_task_id=task_id, owner=user, feature="catalog_import_ai").exists()

    payload = captured["payload"]
    assert payload["filename"] == "прайс.pdf"
    assert payload["supplier_company_id"] == company.id
    assert payload["dry_run"] is True
    assert payload["storage_path"].startswith("ai_extract_tmp/")
    try:
        with default_storage.open(payload["storage_path"]) as staged:
            assert staged.read() == PDF_BYTES
    finally:
        default_storage.delete(payload["storage_path"])


# ── Рефактор ядра ───────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_frame_core_raises_on_missing_name_column(lookups):
    from sourcing.catalog_import import run_catalog_import_frame

    with pytest.raises(ValueError, match="NAME_COLUMN_NOT_FOUND"):
        run_catalog_import_frame(pd.DataFrame([{"Цена": "10"}]))
