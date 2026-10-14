"""R7 (spec-nomenclature-ux-audit-2026-08-05, раздел «Мёртвый функционал»).

Контракт обещал то, чего пользователь не мог ни задать, ни увидеть:

* окно действия цены (`valid_from`/`valid_until`) жило в модели, но не в API — задать срок
  «цена до конца квартала» было негде вовсе;
* MOQ, срок поставки текстом и деактивацию оффера писал только Excel-импорт: продавец видел
  в публичной карточке условия, которых не находил у себя в форме;
* подпись фото (`alt_text`) и имя документа принимались эндпоинтами, но интерфейс их не слал —
  alt приезжал пустым, а документ всегда назывался именем файла;
* `Product.manufacturer` помечен DEPRECATED и НЕ отдаётся сериализаторами — тип на клиенте
  объявлял его годами, то есть контракт врал.

Тесты сторожат ИМЕННО контракт: поля читаются и пишутся, перевёрнутое окно отвергается
кодом, а мёртвое поле не всплывает обратно в выдачу.
"""

import datetime
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import Company, CompanyMember, CompanyRole, CompanyType, CustomUser, WorkspaceRole
from catalog.models import Product, ProductStatus, SupplierOffer
from catalog.serializers import ProductListSerializer, ProductSerializer
from master_data.models import Currency

pytestmark = pytest.mark.django_db

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
PDF_BYTES = b"%PDF-1.4" + b"\x00" * 64


def _client_for(user) -> APIClient:
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
    return client


@pytest.fixture
def seller_world(db):
    published, _ = ProductStatus.objects.get_or_create(
        code="PUBLISHED", defaults={"name": "Опубликован", "sort_order": 20}
    )
    ProductStatus.objects.get_or_create(code="DRAFT", defaults={"name": "Черновик", "sort_order": 10})
    supplier_type, _ = CompanyType.objects.get_or_create(
        code="SUPPLIER", defaults={"name": "Поставщик", "sort_order": 20}
    )
    workspace_role, _ = WorkspaceRole.objects.get_or_create(
        code="SALES_MANAGER", defaults={"name": "Менеджер", "sort_order": 20}
    )
    currency, _ = Currency.objects.get_or_create(code="UZS", defaults={"name": "Сум", "symbol": "so'm"})

    company = Company.objects.create(name="ООО Р7", inn="9700000001")
    company.types.add(supplier_type)

    company_role = CompanyRole.objects.create(
        company=company, name="Каталог", permissions=["catalog.manage", "supply.manage"]
    )  # офферы поставщиков — supply.manage (M1-ERP-05)
    user = CustomUser.objects.create_user(email="seller@r7.test", username="seller@r7.test", password="pw")
    CompanyMember.objects.create(
        user=user,
        company=company,
        role=workspace_role,
        company_roles=[company_role],
        is_active=True,
        is_primary=True,
        can_sell=True,
    )

    product = Product.objects.create(name="Колодка Р7", owner_company=company, status=published)
    offer = SupplierOffer.objects.create(
        product=product, supplier=company, base_price=Decimal("100"), currency=currency
    )
    return {"company": company, "user": user, "product": product, "offer": offer, "currency": currency}


# ── Оффер: поля, которых не было в контракте ────────────────────────────────────────────


def test_offer_read_exposes_commercial_terms(seller_world):
    """Все пять полей волны видны продавцу в ответе — раньше половину отдавала только БД."""
    offer = seller_world["offer"]
    offer.min_order_qty = 25
    offer.delivery_lead_time = "14-21 дн."
    offer.valid_from = "2026-08-01"
    offer.valid_until = "2026-09-30"
    offer.save()

    body = _client_for(seller_world["user"]).get(f"/api/v1/catalog/offers/{offer.pk}/").json()

    assert body["min_order_qty"] == 25
    assert body["delivery_lead_time"] == "14-21 дн."
    assert body["valid_from"] == "2026-08-01"
    assert body["valid_until"] == "2026-09-30"
    assert body["is_active"] is True


def test_offer_write_persists_validity_window_and_moq(seller_world):
    """Продавец задаёт срок действия цены, MOQ и текстовый срок — и они сохраняются."""
    offer = seller_world["offer"]

    response = _client_for(seller_world["user"]).patch(
        f"/api/v1/catalog/offers/{offer.pk}/",
        {
            "min_order_qty": 10,
            "delivery_lead_time": "по согласованию",
            "valid_from": "2026-08-05",
            "valid_until": "2026-12-31",
        },
        format="json",
    )

    assert response.status_code == 200, response.content
    offer.refresh_from_db()
    assert offer.min_order_qty == 10
    assert offer.delivery_lead_time == "по согласованию"
    assert str(offer.valid_from) == "2026-08-05"
    assert str(offer.valid_until) == "2026-12-31"


def test_offer_can_be_taken_off_sale_without_deleting(seller_world):
    """Снятие с продажи — тумблер, а не удаление: на оффер ссылаются исторические КП."""
    offer = seller_world["offer"]

    response = _client_for(seller_world["user"]).patch(
        f"/api/v1/catalog/offers/{offer.pk}/", {"is_active": False}, format="json"
    )

    assert response.status_code == 200, response.content
    offer.refresh_from_db()
    assert offer.is_active is False
    assert SupplierOffer.objects.filter(pk=offer.pk).exists()


def test_inverted_validity_window_rejected_with_code(seller_world):
    """«Действует до» раньше «действует с» — отказ стабильным кодом, а не молчаливой записью."""
    response = _client_for(seller_world["user"]).patch(
        f"/api/v1/catalog/offers/{seller_world['offer'].pk}/",
        {"valid_from": "2026-09-01", "valid_until": "2026-08-01"},
        format="json",
    )

    assert response.status_code == 400
    assert "OFFER_VALIDITY_RANGE_INVALID" in str(response.json()["detail"])


def test_inverted_window_cannot_be_assembled_by_two_patches(seller_world):
    """Вторая граница сверяется с УЖЕ сохранённой первой — иначе окно переворачивалось PATCH'ем."""
    offer = seller_world["offer"]
    offer.valid_from = "2026-09-01"
    offer.save()

    response = _client_for(seller_world["user"]).patch(
        f"/api/v1/catalog/offers/{offer.pk}/", {"valid_until": "2026-08-01"}, format="json"
    )

    assert response.status_code == 400
    offer.refresh_from_db()
    assert offer.valid_until is None


@pytest.mark.parametrize(
    "payload",
    [
        {"valid_from": "2026-08-01", "valid_until": None},
        {"valid_from": None, "valid_until": "2026-08-01"},
        {"valid_from": None, "valid_until": None},
        {"valid_from": "2026-08-01", "valid_until": "2026-08-01"},
    ],
)
def test_open_validity_boundaries_are_legal(seller_world, payload):
    """Пустая граница — «уже действует» / «бессрочно», а не ошибка (Odoo supplierinfo)."""
    response = _client_for(seller_world["user"]).patch(
        f"/api/v1/catalog/offers/{seller_world['offer'].pk}/", payload, format="json"
    )

    assert response.status_code == 200, response.content


def test_validity_rule_lives_in_the_service_layer():
    """Rule 8: правило окна — функция сервиса, сериализатор её только зовёт."""
    from catalog.services import offer_validity_error

    early, late = datetime.date(2026, 8, 1), datetime.date(2026, 9, 1)
    assert offer_validity_error(late, early) == "OFFER_VALIDITY_RANGE_INVALID"
    assert offer_validity_error(early, late) is None
    assert offer_validity_error(None, None) is None


# ── Медиа: подпись фото и имя документа ─────────────────────────────────────────────────


def test_uploaded_image_keeps_alt_text(seller_world, settings, tmp_path):
    """`alt_text` доезжает до записи и возвращается в ответе — a11y-поле ожило."""
    settings.MEDIA_ROOT = str(tmp_path)
    image = SimpleUploadedFile("brake.png", PNG_BYTES, content_type="image/png")

    response = _client_for(seller_world["user"]).post(
        f"/api/v1/catalog/products/{seller_world['product'].pk}/upload-image/",
        {"image": image, "alt_text": "Тормозная колодка в сборе", "is_main": "true"},
        format="multipart",
    )

    assert response.status_code == 201, response.content
    assert response.json()["alt_text"] == "Тормозная колодка в сборе"
    assert seller_world["product"].images.get().alt_text == "Тормозная колодка в сборе"


def test_uploaded_document_takes_the_given_name(seller_world, settings, tmp_path):
    """Документ называется «Паспорт изделия», а не «scan_0007.pdf»."""
    settings.MEDIA_ROOT = str(tmp_path)
    document = SimpleUploadedFile("scan_0007.pdf", PDF_BYTES, content_type="application/pdf")

    response = _client_for(seller_world["user"]).post(
        f"/api/v1/catalog/products/{seller_world['product'].pk}/upload-document/",
        {"file": document, "name": "Паспорт изделия"},
        format="multipart",
    )

    assert response.status_code == 201, response.content
    assert response.json()["name"] == "Паспорт изделия"
    assert seller_world["product"].documents.get().name == "Паспорт изделия"


def test_document_name_falls_back_to_file_name(seller_world, settings, tmp_path):
    """Поле имени необязательно: пустое — прежнее поведение, а не пустое имя."""
    settings.MEDIA_ROOT = str(tmp_path)
    document = SimpleUploadedFile("passport.pdf", PDF_BYTES, content_type="application/pdf")

    response = _client_for(seller_world["user"]).post(
        f"/api/v1/catalog/products/{seller_world['product'].pk}/upload-document/",
        {"file": document},
        format="multipart",
    )

    assert response.status_code == 201, response.content
    assert response.json()["name"] == "passport.pdf"


# ── Мёртвое поле не всплывает обратно ───────────────────────────────────────────────────


def test_deprecated_manufacturer_stays_out_of_the_product_contract(seller_world):
    """`Product.manufacturer` (DEPRECATED) не отдаётся ни карточкой, ни списком.

    Поле ещё в модели: его читают как ЛЕГАСИ-запасной вариант владения `core/permissions.py`
    и `sourcing/views_attachments.py` (миграция `catalog/0010` уже перелила значения в
    `owner_company`, так что ветка недостижима). Удаление колонки — отдельная волна, которая
    владеет теми файлами. Контракт же обязан молчать о нём и здесь, и на клиенте.
    """
    assert "manufacturer" not in ProductSerializer().fields
    assert "manufacturer" not in ProductListSerializer().fields

    client = _client_for(seller_world["user"])
    detail = client.get(f"/api/v1/catalog/products/{seller_world['product'].pk}/").json()
    row = client.get("/api/v1/catalog/products/").json()["results"][0]

    assert "manufacturer" not in detail
    assert "manufacturer" not in row
    # `manufacturer_part_number` — другое поле (MPN, живое): гарантируем, что не задели его.
    assert "manufacturer_part_number" in detail
