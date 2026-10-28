"""D2-3: операции `/api/v1`, которые зовёт BFF Платформы для «Номенклатура и поставщики», отвечают как обещает выгрузка.

Схема — из кода (`core/tests/openapi_internal.py`), тела запросов — те, что шлёт BFF
(`apps/platform/bff/app/api/erp_catalog.py`), ответы — живые, у ролей с правом на закрытые поля и без него.
"""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from catalog.models import Brigade, HSCode
from catalog.tests.desk_world import build_world
from core.models import ExchangeRate
from core.tests.openapi_fixtures import API, conforms, sends

pytestmark = pytest.mark.django_db

PDF = b"%PDF-1.4\n%%EOF\n"


@pytest.fixture
def world():
    return build_world()


def test_items_list_card_create_and_update_conform(world):
    director, manager = world["clients"]["director"], world["clients"]["manager"]
    conforms(
        director.get(f"{API}catalog/items/", {"q": "кабель", "kind": "stock", "page_size": 5}),
        "/api/v1/catalog/items/",
        "get",
        status=200,
    )
    template = "/api/v1/catalog/items/{id}/"
    conforms(director.get(f"{API}catalog/items/{world['cable'].pk}/"), template, "get", status=200)
    conforms(manager.get(f"{API}catalog/items/{world['cable'].pk}/"), template, "get", status=200)  # цены null
    conforms(manager.get(f"{API}catalog/items/987654/"), template, "get", status=404)
    body = {
        "name": "Монтаж",
        "kind": "service_time",
        "unit_id": world["unit"].pk,
        "vat_rate": "12",
        "category_id": world["category"].pk,
        "description": "d",
    }
    sends("/api/v1/catalog/items/", "post", body)
    conforms(director.post(f"{API}catalog/items/", body, format="json"), "/api/v1/catalog/items/", "post", status=201)
    conforms(manager.post(f"{API}catalog/items/", body, format="json"), "/api/v1/catalog/items/", "post", status=403)
    conforms(
        director.post(f"{API}catalog/items/", {"name": ""}, format="json"), "/api/v1/catalog/items/", "post", status=400
    )
    patch = {"name": "Реле", "vat_rate": None, "unit_id": None, "category_id": None, "kind": "stock", "description": ""}
    sends(template, "patch", patch)
    conforms(
        director.patch(f"{API}catalog/items/{world['relay'].pk}/", patch, format="json"), template, "patch", status=200
    )


def test_suppliers_and_offer_edit_conform(world):
    director, engineer = world["clients"]["director"], world["clients"]["engineer"]
    conforms(director.get(f"{API}catalog/suppliers/", {"q": "север"}), "/api/v1/catalog/suppliers/", "get", status=200)
    template = "/api/v1/catalog/suppliers/{id}/"
    conforms(director.get(f"{API}catalog/suppliers/{world['supplier'].pk}/"), template, "get", status=200)
    conforms(engineer.get(f"{API}catalog/suppliers/{world['supplier'].pk}/"), template, "get", status=200)
    conforms(engineer.get(f"{API}catalog/suppliers/987654/"), template, "get", status=404)
    offer = "/api/v1/catalog/suppliers/{id}/offers/{offer_id}/"
    url = f"{API}catalog/suppliers/{world['supplier'].pk}/offers/{world['offers']['live'].pk}/"
    body = {
        "price": {"amount": "13.00", "currency": "USD"},
        "quota_qty": 10,
        "min_order_qty": 2,
        "in_stock_lead_days": 1,
        "order_lead_days": 7,
        "stock_status": "IN_STOCK",
        "valid_from": "2026-01-01",
        "valid_until": "2030-01-01",
        "is_active": True,
    }
    sends(offer, "patch", body)
    conforms(director.patch(url, body, format="json"), offer, "patch", status=200)
    conforms(engineer.patch(url, {"price": body["price"]}, format="json"), offer, "patch", status=403)
    conforms(director.patch(url, {"valid_from": "2031-01-01"}, format="json"), offer, "patch", status=400)
    conforms(
        director.patch(f"{API}catalog/suppliers/{world['supplier'].pk}/offers/987654/", {}, format="json"),
        offer,
        "patch",
        status=404,
    )


def test_brigades_conform(world):
    director, manager = world["clients"]["director"], world["clients"]["manager"]
    body = {
        "name": "Бригада",
        "kind": "brigade",
        "specialization": "ПНР",
        "headcount": 3,
        "rate": {"amount": "1000", "currency": "UZS"},
        "rate_unit": "day",
        "note": "n",
        "is_active": True,
    }
    sends("/api/v1/catalog/brigades/", "post", body)
    created = director.post(f"{API}catalog/brigades/", body, format="json")
    conforms(created, "/api/v1/catalog/brigades/", "post", status=201)
    conforms(
        manager.post(f"{API}catalog/brigades/", body, format="json"), "/api/v1/catalog/brigades/", "post", status=403
    )
    conforms(
        director.get(f"{API}catalog/brigades/", {"q": "бри", "kind": "brigade", "include_inactive": "1"}),
        "/api/v1/catalog/brigades/",
        "get",
        status=200,
    )
    conforms(manager.get(f"{API}catalog/brigades/"), "/api/v1/catalog/brigades/", "get", status=200)  # rate null
    template = "/api/v1/catalog/brigades/{id}/"
    sends(template, "patch", {**body, "rate": None})
    conforms(
        director.patch(
            f"{API}catalog/brigades/{created.json()['id']}/", {"rate": None, "rate_unit": "hour"}, format="json"
        ),
        template,
        "patch",
        status=200,
    )
    conforms(director.patch(f"{API}catalog/brigades/987654/", {}, format="json"), template, "patch", status=404)


def test_tech_docs_conform(world):
    director, manager = world["clients"]["director"], world["clients"]["manager"]
    file = SimpleUploadedFile("tz.pdf", PDF, content_type="application/pdf")
    created = director.post(
        f"{API}catalog/tech-docs/",
        {"file": file, "kind": "tz", "title": "ТЗ", "product_id": world["relay"].pk},
        format="multipart",
    )
    conforms(created, "/api/v1/catalog/tech-docs/", "post", status=201)
    refused = director.post(
        f"{API}catalog/tech-docs/",
        {"file": SimpleUploadedFile("a.pdf", PDF, content_type="application/pdf")},
        format="multipart",
    )
    conforms(refused, "/api/v1/catalog/tech-docs/", "post", status=400)
    manager_try = manager.post(
        f"{API}catalog/tech-docs/",
        {"file": SimpleUploadedFile("a.pdf", PDF, content_type="application/pdf"), "product_id": world["relay"].pk},
        format="multipart",
    )
    conforms(manager_try, "/api/v1/catalog/tech-docs/", "post", status=403)
    conforms(
        manager.get(f"{API}catalog/tech-docs/", {"q": "тз", "kind": "tz", "product": world["relay"].pk}),
        "/api/v1/catalog/tech-docs/",
        "get",
        status=200,
    )
    file_template = "/api/v1/catalog/tech-docs/{id}/file/"
    streamed = manager.get(f"{API}catalog/tech-docs/{created.json()['id']}/file/")
    assert streamed.status_code == 200
    conforms(manager.get(f"{API}catalog/tech-docs/987654/file/"), file_template, "get", status=404)
    template = "/api/v1/catalog/tech-docs/{id}/"
    conforms(manager.delete(f"{API}catalog/tech-docs/{created.json()['id']}/"), template, "delete", status=403)
    conforms(director.delete(f"{API}catalog/tech-docs/{created.json()['id']}/"), template, "delete", status=204)


def test_reference_data_conform(world):
    director, manager = world["clients"]["director"], world["clients"]["manager"]
    body = {
        "code": "8536",
        "name": "Аппаратура",
        "unit_name": "кг",
        "extra_unit_name": "шт",
        "valid_from": "2020-01-01",
        "valid_until": None,
    }
    sends("/api/v1/master-data/hs-codes/", "post", body)
    created = director.post(f"{API}master-data/hs-codes/", body, format="json")
    conforms(created, "/api/v1/master-data/hs-codes/", "post", status=201)
    conforms(
        director.post(f"{API}master-data/hs-codes/", body, format="json"),
        "/api/v1/master-data/hs-codes/",
        "post",
        status=409,
    )
    conforms(
        manager.post(f"{API}master-data/hs-codes/", body, format="json"),
        "/api/v1/master-data/hs-codes/",
        "post",
        status=403,
    )
    conforms(
        manager.get(f"{API}master-data/hs-codes/", {"q": "85", "level": 4, "active": "1"}),
        "/api/v1/master-data/hs-codes/",
        "get",
        status=200,
    )
    template = "/api/v1/master-data/hs-codes/{id}/"
    conforms(
        director.patch(
            f"{API}master-data/hs-codes/{HSCode.objects.get(code='8536').pk}/",
            {"name": "Новое", "valid_until": "2040-01-01"},
            format="json",
        ),
        template,
        "patch",
        status=200,
    )
    conforms(director.patch(f"{API}master-data/hs-codes/987654/", {}, format="json"), template, "patch", status=404)

    ExchangeRate.objects.create(
        currency=world["usd"], rate_to_uzs="12650.5", rate_date=timezone.localdate(), source="CBU"
    )
    conforms(manager.get(f"{API}exchange-rates/", {"currency": "USD"}), "/api/v1/exchange-rates/", "get", status=200)

    brand = director.post(
        f"{API}catalog/manufacturers/",
        {"name": "Brand-D23", "website": "https://example.test", "is_active": True},
        format="json",
    )
    conforms(brand, "/api/v1/catalog/manufacturers/", "post", status=201)
    conforms(
        director.post(f"{API}catalog/manufacturers/", {"name": "brand-d23"}, format="json"),
        "/api/v1/catalog/manufacturers/",
        "post",
        status=400,
    )
    conforms(
        director.patch(f"{API}catalog/manufacturers/{brand.json()['id']}/", {"is_active": False}, format="json"),
        "/api/v1/catalog/manufacturers/{id}/",
        "patch",
        status=200,
    )
    assert Brigade.objects.count() == 0
