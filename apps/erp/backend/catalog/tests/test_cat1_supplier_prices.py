"""CAT-1 (L0-2): поставщик, цена поставщика, загрузка прайса сотрудником, чужие карточки не перезаписываются.

Мир — `desk_world` (D2-3): своя компания, сотрудники с наборами прав ролей Платформы. Названия заводов и товаров выдуманы.
Эталоны: SAP Ariba catalog upload (загрузка → сопоставление → одобрение), Odoo `product.supplierinfo` (цена поставщика с
валютой, MOQ, сроком и окном действия), Coupa (срок действия цены).
"""

import base64
import uuid
from datetime import date
from decimal import Decimal
from io import BytesIO
from types import SimpleNamespace

import pandas as pd
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from parties.models import Company, CompanyType

from catalog.models import Category, Manufacturer, Product, ProductFieldProposal, ProductStatus, SupplierOffer
from catalog.tests.desk_world import build_world
from core.models import Country, DeliveryBasis
from sourcing.catalog_import import run_catalog_import

pytestmark = pytest.mark.django_db

IMPORT_URL = "/api/v1/sourcing/import-catalog/"


@pytest.fixture
def world():
    data = build_world()
    data["uz"] = Country.objects.get_or_create(code="UZ", defaults={"name": "Узбекистан"})[0]
    data["de"] = Country.objects.get_or_create(code="DE", defaults={"name": "Германия"})[0]
    return data


def _xlsx(records) -> bytes:
    buffer = BytesIO()
    pd.DataFrame(records).to_excel(buffer, index=False)
    return buffer.getvalue()


def _plant(name, **extra) -> Company:
    company = Company.objects.create(name=name, **extra)
    company.types.add(CompanyType.objects.get_or_create(code="MANUFACTURER", defaults={"name": "Изготовитель"})[0])
    return company


def _row(**extra):
    row = {
        "Наименование": "Вентиль запорный ВЗ-50",
        "Бренд": "Аквилон",
        "Артикул производителя": "AQ-50",
        "Цена": "120.00",
        "Валюта": "USD",
        "Мин. заказ": "10",
        "Срок поставки": "30 дн.",
    }
    row.update(extra)
    return row


def _upload(world, who, content, monkeypatch, **params):
    """POST загрузки; задача Celery выполняется сразу тем же движком (как воркер)."""
    captured = {}

    def delay(b64, supplier_id, dry_run, **options):
        captured["result"] = run_catalog_import(base64.b64decode(b64), supplier_id, dry_run, **options)
        captured["options"] = {"supplier_company_id": supplier_id, **options}
        return SimpleNamespace(id=uuid.uuid4().hex)

    monkeypatch.setattr("sourcing.views_imports.process_catalog_import.delay", delay)
    body = {"file": SimpleUploadedFile("price.xlsx", content), **params}
    response = world["clients"][who].post(IMPORT_URL, body, format="multipart")
    return response, captured


# --- поставщик ---------------------------------------------------------------------------------------------------


def test_foreign_supplier_without_tin_is_created_with_registration_number(world):
    body = {
        "name": "Werk Nordlicht GmbH",
        "country_id": world["de"].pk,
        "registration_number": "HRB 000001",
        "currency": "EUR",
        "contact_person": "Отдел продаж",
        "email": "sales@nordlicht.example",
        "is_manufacturer": True,
    }
    from core.models import Currency

    Currency.objects.get_or_create(code="EUR", defaults={"name": "Euro", "symbol": "€"})
    created = world["clients"]["supply"].post("/api/v1/catalog/suppliers/", body, format="json")
    assert created.status_code == 201, created.content
    card = created.json()
    assert card["tin"] == "" and card["registration_number"] == "HRB 000001"
    assert card["currency"] == "EUR" and card["country"] == "Германия" and card["is_manufacturer"] is True
    company = Company.objects.get(pk=card["id"])
    assert company.inn is None and set(company.types.values_list("code", flat=True)) == {"SUPPLIER", "MANUFACTURER"}

    again = world["clients"]["supply"].post("/api/v1/catalog/suppliers/", body, format="json")
    assert again.status_code == 409 and again.json() == {"detail": "SUPPLIER_EXISTS"}


def test_supplier_needs_tin_or_registration_number_and_supply_right(world):
    no_id = world["clients"]["supply"].post("/api/v1/catalog/suppliers/", {"name": "Завод без номера"}, format="json")
    assert no_id.status_code == 400 and no_id.json() == {"detail": "SUPPLIER_ID_REQUIRED"}
    bad_tin = world["clients"]["supply"].post(
        "/api/v1/catalog/suppliers/", {"name": "Завод", "tin": "12"}, format="json"
    )
    assert bad_tin.json() == {"detail": "TIN_INVALID"}
    for who in ("manager", "accountant", "viewer"):
        refused = world["clients"][who].post(
            "/api/v1/catalog/suppliers/", {"name": "Завод", "tin": "301234567"}, format="json"
        )
        assert refused.status_code == 403, who
    resident = world["clients"]["supply"].post(
        "/api/v1/catalog/suppliers/", {"name": "Завод Восход", "tin": "301234567", "country_id": world["uz"].pk}
    )
    assert resident.status_code == 201 and resident.json()["tin"] == "301234567"


def test_supplier_card_lists_supplied_and_manufactured_brands(world):
    plant = _plant("Завод Аквилон", inn="301111111")
    brand = Manufacturer.objects.create(name="Аквилон", company=plant)
    product = Product.objects.create(name="Вентиль", brand=brand, manufacturer_part_number="AQ-1")
    SupplierOffer.objects.create(product=product, supplier=world["supplier"], base_price=Decimal("1"))
    supplier = world["clients"]["manager"].get(f"/api/v1/catalog/suppliers/{world['supplier'].pk}/").json()
    assert supplier["brands"] == [{"id": brand.pk, "name": "Аквилон"}]
    made = world["clients"]["manager"].get(f"/api/v1/catalog/suppliers/{plant.pk}/").json()
    assert made["manufactured_brands"] == [{"id": brand.pk, "name": "Аквилон"}] and made["brands"] == []


# --- цена поставщика вручную и история ----------------------------------------------------------------------------


def test_offer_create_with_incoterms_and_history(world):
    basis = DeliveryBasis.objects.get_or_create(code="FCA", defaults={"name": "Free Carrier"})[0]
    plant = _plant("Завод Полярный", inn="302222222")
    path = f"/api/v1/catalog/suppliers/{plant.pk}/offers/"
    body = {
        "product_id": world["relay"].pk,
        "price": {"amount": "250.00", "currency": "USD"},
        "delivery_basis": "FCA",
        "min_order_qty": 5,
        "order_lead_days": 45,
        "valid_from": "2026-11-01",
        "valid_until": "2027-01-31",
        "source": "rfq_reply",
    }
    for who in ("engineer", "manager"):  # без права на цены или без supply.manage
        assert world["clients"][who].post(path, body, format="json").status_code == 403, who
    created = world["clients"]["supply"].post(path, body, format="json")
    assert created.status_code == 201, created.content
    offer = created.json()
    assert offer["price"] == {"amount": "250.00", "currency": "USD"}
    assert (offer["delivery_basis"], offer["source"], offer["min_order_qty"]) == (basis.code, "rfq_reply", 5)
    assert world["clients"]["supply"].post(path, body, format="json").json() == {"detail": "OFFER_EXISTS"}

    world["clients"]["supply"].patch(
        f"{path}{offer['id']}/", {"price": {"amount": "260.00", "currency": "USD"}, "source": "manual"}, format="json"
    )
    history = world["clients"]["supply"].get(f"{path}{offer['id']}/history/").json()
    assert [h["price"]["amount"] for h in history] == ["260.00", "250.00"]
    # «Кто» приходит из контекста pghistory; в тестах `_pgh_attach_context()` — заглушка (conftest), поле пусто.
    assert history[0]["source"] == "manual" and history[1]["source"] == "rfq_reply"
    hidden = world["clients"]["engineer"].get(f"{path}{offer['id']}/history/").json()
    assert [h["price"] for h in hidden] == [None, None]


# --- загрузка прайса сотрудником --------------------------------------------------------------------------------


def test_staff_import_writes_offers_of_the_chosen_supplier_with_validity(world, monkeypatch):
    plant = _plant("Werk Nordlicht GmbH", registration_number="HRB 000001", country=world["de"])
    response, captured = _upload(
        world,
        "supply",
        _xlsx([_row()]),
        monkeypatch,
        supplier_company_id=str(plant.pk),
        valid_from="2026-11-01",
        valid_until="2027-03-31",
    )
    assert response.status_code == 202, response.content
    result = captured["result"]
    assert (result["created"], result["offers_created"], result["error_count"]) == (1, 1, 0)
    offer = SupplierOffer.objects.get(supplier=plant)
    assert offer.base_price == Decimal("120.00") and offer.currency.code == "USD" and offer.min_order_qty == 10
    assert (offer.valid_from, offer.valid_until) == (date(2026, 11, 1), date(2027, 3, 31))
    assert offer.source == SupplierOffer.Source.PRICE_LIST
    product = offer.product
    assert product.owner_company_id == world["own"].pk and product.source_supplier_id == plant.pk
    assert product.status.code == "DRAFT"
    assert not SupplierOffer.objects.filter(supplier=world["own"]).exists()


def test_import_rejects_wrong_supplier_bad_dates_and_missing_rights(world, monkeypatch):
    plant = _plant("Завод Север-2", inn="303333333")
    content = _xlsx([_row()])
    client_company = Company.objects.create(name="Клиент Юг", inn="304444444")
    client_company.types.add(CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Клиент"})[0])
    for supplier_id, code in (
        (client_company.pk, "SUPPLIER_NOT_FOUND"),
        (world["own"].pk, "SUPPLIER_NOT_FOUND"),
        ("abc", "SUPPLIER_INVALID"),
    ):
        response, _ = _upload(world, "supply", content, monkeypatch, supplier_company_id=str(supplier_id))
        assert response.status_code == 400 and response.json() == {"detail": code}, supplier_id
    response, _ = _upload(
        world,
        "supply",
        content,
        monkeypatch,
        supplier_company_id=str(plant.pk),
        valid_from="2027-01-01",
        valid_until="2026-01-01",
    )
    assert response.json() == {"detail": "OFFER_VALIDITY_RANGE_INVALID"}
    # Каталог без права на цены поставщиков (гл. инженер) и без права каталога (менеджер).
    response, _ = _upload(world, "engineer", content, monkeypatch, supplier_company_id=str(plant.pk))
    assert response.status_code == 403 and response.json() == {"detail": "SUPPLIER_PRICES_REQUIRED"}
    response, _ = _upload(world, "manager", content, monkeypatch, supplier_company_id=str(plant.pk))
    assert response.status_code == 403


def test_second_plant_does_not_change_first_plants_card_and_proposes_instead(world, monkeypatch):
    plant_a = _plant("Завод Аквилон", inn="305555555")
    plant_b = _plant("Werk Kristall AG", registration_number="CHE-000.000.001", country=world["de"])
    second = Category.objects.create(name="Арматура трубопроводная")
    _upload(
        world,
        "supply",
        _xlsx([_row(Категория="Электрооборудование")]),
        monkeypatch,
        supplier_company_id=str(plant_a.pk),
    )
    card = Product.objects.get(manufacturer_part_number="AQ-50")
    card.hs_code = "8481806310"
    card.save()

    changed = _row(**{"Наименование": "Клапан AQ-50 (Kristall)", "Категория": second.name, "Код ТН ВЭД": "8481808199"})
    response, captured = _upload(world, "supply", _xlsx([changed]), monkeypatch, supplier_company_id=str(plant_b.pk))
    assert response.status_code == 202
    card.refresh_from_db()
    assert (card.name, card.category.name, card.hs_code) == (
        "Вентиль запорный ВЗ-50",
        "Электрооборудование",
        "8481806310",
    )
    assert SupplierOffer.objects.filter(product=card).count() == 2  # предложение завода Б добавлено
    proposals = {p.field: p for p in ProductFieldProposal.objects.filter(product=card, supplier=plant_b)}
    assert set(proposals) == {"name", "category", "hs_code"}
    assert captured["result"]["proposal_count"] == 3

    # Повторная загрузка того же файла — без дублей предложений, карточек и цен.
    _upload(world, "supply", _xlsx([changed]), monkeypatch, supplier_company_id=str(plant_b.pk))
    assert ProductFieldProposal.objects.filter(product=card, status="pending").count() == 3
    assert Product.objects.filter(manufacturer_part_number="AQ-50").count() == 1
    assert SupplierOffer.objects.filter(product=card).count() == 2

    # Карточка видит изменения на одобрении; «Принять» применяет, «Отклонить» больше не предлагает.
    detail = world["clients"]["supply"].get(f"/api/v1/catalog/items/{card.pk}/").json()
    assert detail["proposals_count"] == 3 and {p["field"] for p in detail["proposals"]} == set(proposals)
    accepted = world["clients"]["supply"].post(f"/api/v1/catalog/field-proposals/{proposals['category'].pk}/accept/")
    assert accepted.status_code == 200 and accepted.json()["category"]["name"] == second.name
    rejected = world["clients"]["supply"].post(f"/api/v1/catalog/field-proposals/{proposals['name'].pk}/reject/")
    assert rejected.status_code == 200 and rejected.json()["name"] == "Вентиль запорный ВЗ-50"
    again = world["clients"]["supply"].post(f"/api/v1/catalog/field-proposals/{proposals['name'].pk}/accept/")
    assert again.status_code == 409 and again.json() == {"detail": "PROPOSAL_DECIDED"}
    _upload(world, "supply", _xlsx([changed]), monkeypatch, supplier_company_id=str(plant_b.pk))
    assert not ProductFieldProposal.objects.filter(product=card, field="name", status="pending").exists()
    assert (
        world["clients"]["manager"]
        .post(f"/api/v1/catalog/field-proposals/{proposals['hs_code'].pk}/accept/")
        .status_code
        == 403
    )


def test_reupload_by_same_plant_updates_its_own_draft_card_and_does_not_duplicate(world, monkeypatch):
    plant = _plant("Завод Восток", inn="306666666")
    no_keys = {"Наименование": "Прокладка паронитовая", "Артикул поставщика": "VS-7", "Цена": "3.50", "Валюта": "USD"}
    first, _ = _upload(world, "supply", _xlsx([_row(), no_keys]), monkeypatch, supplier_company_id=str(plant.pk))
    assert first.status_code == 202
    _, captured = _upload(
        world,
        "supply",
        _xlsx([_row(Описание="Новое описание", Цена="125.00"), {**no_keys, "Цена": "3.80"}]),
        monkeypatch,
        supplier_company_id=str(plant.pk),
    )
    result = captured["result"]
    assert (result["created"], result["updated"], result["offers_updated"], result["proposal_count"]) == (0, 2, 2, 0)
    assert Product.objects.filter(source_supplier=plant).count() == 2
    assert Product.objects.get(manufacturer_part_number="AQ-50").description == "Новое описание"
    assert SupplierOffer.objects.get(supplier=plant, supplier_sku="VS-7").base_price == Decimal("3.80")


def test_published_card_is_never_overwritten_even_by_its_own_supplier(world, monkeypatch):
    plant = _plant("Завод Запад", inn="307777777")
    _upload(world, "supply", _xlsx([_row()]), monkeypatch, supplier_company_id=str(plant.pk))
    card = Product.objects.get(manufacturer_part_number="AQ-50")
    card.status = ProductStatus.objects.get(code="PUBLISHED")
    card.save()
    _upload(world, "supply", _xlsx([_row(Наименование="Другое имя")]), monkeypatch, supplier_company_id=str(plant.pk))
    card.refresh_from_db()
    assert card.name == "Вентиль запорный ВЗ-50"
    assert ProductFieldProposal.objects.filter(product=card, field="name", status="pending").exists()


def test_validity_columns_override_form_and_bad_dates_are_row_errors(world, monkeypatch):
    plant = _plant("Завод Юг", inn="308888888")
    rows = [
        _row(**{"Действует до": "31.12.2026"}),
        _row(**{"Артикул производителя": "AQ-51", "Действует до": "не дата"}),
    ]
    _, captured = _upload(
        world, "supply", _xlsx(rows), monkeypatch, supplier_company_id=str(plant.pk), valid_until="2027-06-30"
    )
    assert captured["result"]["errors"] == [{"row": 3, "message": "VALID_DATE_INVALID"}]
    assert SupplierOffer.objects.get(supplier=plant).valid_until == date(2026, 12, 31)


def test_dry_run_reports_without_writing(world, monkeypatch):
    plant = _plant("Завод Проверка", inn="309999999")
    _, captured = _upload(
        world, "supply", _xlsx([_row()]), monkeypatch, supplier_company_id=str(plant.pk), dry_run="true"
    )
    assert captured["result"]["dry_run"] is True and captured["result"]["offers_created"] == 1
    assert not SupplierOffer.objects.filter(supplier=plant).exists()
    assert not Product.objects.filter(manufacturer_part_number="AQ-50").exists()


def test_row_without_currency_takes_suppliers_currency(world, monkeypatch):
    plant = _plant("Завод Валюта", inn="301010101", default_currency=world["uzs"])
    _upload(world, "supply", _xlsx([_row(Валюта="")]), monkeypatch, supplier_company_id=str(plant.pk))
    assert SupplierOffer.objects.get(supplier=plant).currency.code == "UZS"


# --- карточка: бренд, артикул изготовителя, ТН ВЭД, публикация -------------------------------------------------


def test_item_brand_mpn_hs_are_editable_and_publish_follows_completeness(world):
    brand = Manufacturer.objects.create(name="Аквилон")
    path = f"/api/v1/catalog/items/{world['cable'].pk}/"
    edited = world["clients"]["supply"].patch(
        path, {"brand_id": brand.pk, "manufacturer_part_number": "AQ-77", "hs_code": "8544429007"}, format="json"
    )
    assert edited.status_code == 200, edited.content
    card = edited.json()
    assert (card["brand_id"], card["brand"], card["manufacturer_part_number"], card["hs_code"]) == (
        brand.pk,
        "Аквилон",
        "AQ-77",
        "8544429007",
    )
    assert world["clients"]["supply"].patch(path, {"hs_code": "12a"}, format="json").json() == {
        "detail": "ITEM_HS_CODE_INVALID"
    }
    assert world["clients"]["manager"].post(f"{path}publish/").status_code == 403


def test_publish_refuses_incomplete_card_and_publishes_complete_one(world, monkeypatch):
    bare = Product.objects.create(name="Пустая карточка")  # без владельца: публикует сотрудник своей компании
    path = f"/api/v1/catalog/items/{bare.pk}/"
    card = world["clients"]["supply"].get(path).json()
    assert card["publish"]["publishable"] is False and card["publish"]["missing"]
    refused = world["clients"]["supply"].post(f"{path}publish/")
    assert refused.status_code == 409 and refused.json() == {"detail": "PRODUCT_INCOMPLETE"}

    monkeypatch.setattr(
        "catalog.publishing.completeness",
        lambda product: {"percent": 100, "missing": [], "threshold": 100, "is_publishable": True},
    )
    published = world["clients"]["supply"].post(f"{path}publish/")
    assert published.status_code == 200 and published.json()["status"] == "PUBLISHED"
    bare.refresh_from_db()
    assert bare.owner_company_id == world["own"].pk
    back = world["clients"]["supply"].post(f"{path}unpublish/")
    assert back.status_code == 200 and back.json()["status"] == "DRAFT"


# --- ИИ: любой файл, проверка человеком, «Применить» без второго вызова модели -----------------------------------


def test_ai_import_takes_supplier_and_applies_only_own_checked_rows(world, monkeypatch, settings):
    from sourcing.ai_rows import save_rows

    settings.AI_IMPORT_ENABLED = True
    plant = _plant("Завод Фото", inn="302020202")
    captured = {}

    def apply_async(args=None, task_id=None, **kwargs):
        captured.update(payload=args[1])
        return SimpleNamespace(id=task_id)

    monkeypatch.setattr("sourcing.tasks_ai.run_ai_job.apply_async", apply_async)
    url = f"/api/v1/sourcing/import-catalog-ai/?supplier_company_id={plant.pk}&valid_until=2027-01-31&dry_run=true"
    pdf = SimpleUploadedFile("price.pdf", b"%PDF-1.4\n%%EOF\n", content_type="application/pdf")
    response = world["clients"]["supply"].post(url, {"file": pdf}, format="multipart")
    assert response.status_code == 202, response.content
    payload = captured["payload"]
    assert (payload["supplier_company_id"], payload["valid_until"], payload["dry_run"]) == (plant.pk, "2027-01-31", True)
    assert payload["owner_company_id"] == world["own"].pk

    foreign = save_rows([{"Наименование": "x"}], world["users"]["director"].pk)
    apply_url = f"/api/v1/sourcing/import-catalog-ai/?supplier_company_id={plant.pk}&rows_token={foreign}"
    refused = world["clients"]["supply"].post(apply_url, {}, format="multipart")
    assert refused.status_code == 400 and refused.json() == {"detail": "ROWS_TOKEN_INVALID"}
    own = save_rows([{"Наименование": "x"}], world["users"]["supply"].pk)
    accepted = world["clients"]["supply"].post(
        f"/api/v1/sourcing/import-catalog-ai/?supplier_company_id={plant.pk}&rows_token={own}", {}, format="multipart"
    )
    assert accepted.status_code == 202 and captured["payload"]["rows_token"] == own
