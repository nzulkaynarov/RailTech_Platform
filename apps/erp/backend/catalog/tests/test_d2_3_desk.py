"""D2-3 «Номенклатура и поставщики»: позиции, поставщики и предложения, бригады, техдокументация, справочники.

Матрица по ролям каталога Платформы (мир — `desk_world`): чтение — любой сотрудник бэк-офиса; запись — права ERP;
закрытые поля (цены поставщиков, ставки бригад) режет сам ERP, поэтому каждый тест «без права» бьёт в ERP напрямую,
минуя BFF.
"""

import json
from datetime import timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from parties.models import CompanySettings

from accounts.constants import ALL_PERMISSIONS
from catalog.desk import tech_docs
from catalog.models import Brigade, HSCode, Manufacturer, Product, TechDocument
from catalog.tests.desk_world import build_world
from core.models import ExchangeRate

pytestmark = pytest.mark.django_db

PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
zone_services = pytest.mark.skipif(
    "quote.visa_services" not in ALL_PERMISSIONS, reason="зона услуг расчёта приходит с D2-1 (PR #289)"
)


@pytest.fixture
def world():
    return build_world()


def get(world, who, path, **params):
    return world["clients"][who].get(f"/api/v1/{path}", params)


def send(world, who, method, path, body=None, **kwargs):
    return getattr(world["clients"][who], method)(
        f"/api/v1/{path}", body, format=kwargs.pop("format", "json"), **kwargs
    )


# --- позиции -----------------------------------------------------------------------------------------------------


def test_items_list_reads_for_every_staff_role_and_never_carries_prices(world):
    for who in world["clients"]:
        response = get(world, who, "catalog/items/")
        assert response.status_code == 200, who
        assert response.json()["count"] == 3
        assert b"12.50" not in response.content and b"310.00" not in response.content, who


def test_items_list_search_and_type_filters(world):
    assert [r["name"] for r in get(world, "manager", "catalog/items/", q="кабель").json()["results"]] == [
        "Кабель силовой ВВГнг 3×2,5"
    ]
    by_kind = {
        kind: get(world, "manager", "catalog/items/", kind=kind).json()
        for kind in ("stock", "on_order", "service_time")
    }
    assert [r["name"] for r in by_kind["stock"]["results"]] == ["Кабель силовой ВВГнг 3×2,5"]
    assert [r["name"] for r in by_kind["on_order"]["results"]] == ["Реле защиты РЗ-1"]
    assert [r["name"] for r in by_kind["service_time"]["results"]] == ["Пусконаладочные работы"]
    assert get(world, "manager", "catalog/items/", kind="service_fixed").json()["count"] == 0
    in_category = get(world, "manager", "catalog/items/", category=world["category"].pk).json()
    assert [r["id"] for r in in_category["results"]] == [world["cable"].pk]


def test_items_row_has_type_unit_vat_and_offers_summary(world):
    CompanySettings.objects.create(company=world["own"], default_vat_rate="12.00")
    world["relay"].vat_rate = "0.00"
    world["relay"].save()
    rows = {r["name"]: r for r in get(world, "director", "catalog/items/", page_size=50).json()["results"]}
    cable = rows["Кабель силовой ВВГнг 3×2,5"]
    assert (
        cable["kind"] == "stock"
        and cable["unit"]["code"] == "pcs"
        and cable["category"]["name"] == "Электрооборудование"
    )
    assert (cable["vat_rate"], cable["vat_effective"]) == (None, "12.00")
    assert rows["Реле защиты РЗ-1"]["vat_effective"] == "0.00"
    assert cable["offers_count"] == 1 and cable["nearest_valid_until"] is not None
    assert rows["Пусконаладочные работы"]["nearest_valid_until"] is None  # единственное предложение истекло


def test_item_card_hides_supplier_prices_without_the_right(world):
    path = f"catalog/items/{world['cable'].pk}/"
    for who in ("engineer", "manager", "accountant", "viewer"):
        response = get(world, who, path)
        body = response.json()
        assert response.status_code == 200 and body["prices_visible"] is False, who
        assert [o["price"] for o in body["offers"]] == [None], who
        assert b"12.50" not in response.content, who
    for who in ("supply", "director"):
        body = get(world, who, path).json()
        assert body["prices_visible"] is True
        assert body["offers"][0]["price"] == {"amount": "12.50", "currency": "USD"}
        assert body["offers"][0]["quota_qty"] == 500 and body["offers"][0]["validity"] == "ok"


def test_item_card_marks_expiring_and_expired_offers(world):
    assert get(world, "supply", f"catalog/items/{world['relay'].pk}/").json()["offers"][0]["validity"] == "expiring"
    assert (
        get(world, "supply", f"catalog/items/{world['commissioning'].pk}/").json()["offers"][0]["validity"] == "expired"
    )


def test_item_create_needs_catalog_manage_and_sets_service_policy(world):
    body = {"name": "Монтаж шкафа", "kind": "service_milestones", "unit_id": world["unit"].pk, "vat_rate": "12"}
    for who in ("manager", "accountant", "viewer"):
        refused = send(world, who, "post", "catalog/items/", body)
        assert refused.status_code == 403 and refused.json() == {"detail": "ROLE_NOT_PERMITTED"}, who
    created = send(world, "engineer", "post", "catalog/items/", body)
    assert created.status_code == 201
    card = created.json()
    assert (
        card["kind"] == "service_milestones"
        and card["is_service"]
        and card["vat_rate"] == "12.00"
        and card["status"] == "DRAFT"
    )
    assert Product.objects.get(pk=card["id"]).fulfillment_policy == "milestones"
    assert card["offers"] == [] and card["prices_visible"] is False


@pytest.mark.parametrize(
    "body, code",
    [
        ({"name": " ", "kind": "stock"}, "ITEM_NAME_REQUIRED"),
        ({"name": "X", "kind": "stock", "vat_rate": "120"}, "VAT_RATE_INVALID"),
        ({"name": "X", "kind": "stock", "vat_rate": "abc"}, "VAT_RATE_INVALID"),
        ({"name": "X", "kind": "stock", "unit_id": 987654}, "UNIT_NOT_FOUND"),
        ({"name": "X", "kind": "stock", "category_id": 987654}, "CATEGORY_NOT_FOUND"),
        ({"kind": "stock"}, "ITEM_NAME_REQUIRED"),
    ],
)
def test_item_create_refusals(world, body, code):
    response = send(world, "supply", "post", "catalog/items/", body)
    assert response.status_code == 400 and response.json() == {"detail": code}


def test_item_update_changes_vat_unit_and_kind_and_rejects_the_unprivileged(world):
    path = f"catalog/items/{world['relay'].pk}/"
    assert send(world, "manager", "patch", path, {"vat_rate": "5"}).status_code == 403
    changed = send(world, "supply", "patch", path, {"vat_rate": "5", "kind": "service_fixed", "name": "Реле (услуга)"})
    assert (
        changed.status_code == 200
        and changed.json()["vat_rate"] == "5.00"
        and changed.json()["kind"] == "service_fixed"
    )
    reset = send(world, "supply", "patch", path, {"vat_rate": None})
    assert reset.json()["vat_rate"] is None
    assert send(world, "supply", "patch", path, {"unit_id": 987654}).json() == {"detail": "UNIT_NOT_FOUND"}
    assert send(world, "supply", "patch", "catalog/items/987654/", {"vat_rate": "5"}).status_code == 404


def test_items_require_a_staff_session(world):
    from rest_framework.test import APIClient

    assert APIClient().get("/api/v1/catalog/items/").status_code == 401
    assert APIClient().post("/api/v1/catalog/items/", {"name": "X", "kind": "stock"}, format="json").status_code == 401


# --- поставщики --------------------------------------------------------------------------------------------------


def test_suppliers_list_summarises_offers_and_excludes_own_company(world):
    page = get(world, "manager", "catalog/suppliers/").json()
    assert [r["name"] for r in page["results"]] == ["ООО Поставщик Север"]
    row = page["results"][0]
    assert (row["offers_count"], row["expired_count"], row["expiring_count"]) == (3, 1, 1)
    assert row["nearest_valid_until"] == str(timezone.localdate() + timedelta(days=5))
    assert get(world, "manager", "catalog/suppliers/", q="нет такого").json()["count"] == 0
    assert b"12.50" not in json.dumps(page).encode()


def test_supplier_card_shows_terms_to_all_and_prices_only_with_the_right(world):
    path = f"catalog/suppliers/{world['supplier'].pk}/"
    for who in ("engineer", "manager", "accountant"):
        body = get(world, who, path).json()
        assert body["prices_visible"] is False and all(o["price"] is None for o in body["offers"]), who
        assert {o["product"]["name"]: o["quota_qty"] for o in body["offers"]}["Кабель силовой ВВГнг 3×2,5"] == 500
        assert body["contact_person"] == "Менеджер Север"
    body = get(world, "supply", path).json()
    prices = {o["product"]["name"]: o["price"]["amount"] for o in body["offers"]}
    assert prices == {
        "Кабель силовой ВВГнг 3×2,5": "12.50",
        "Реле защиты РЗ-1": "310.00",
        "Пусконаладочные работы": "1500.00",
    }
    assert get(world, "supply", f"catalog/suppliers/{world['own'].pk}/").status_code == 404


def test_offer_terms_edit_needs_supply_manage_and_price_needs_the_price_right(world):
    live = world["offers"]["live"]
    path = f"catalog/suppliers/{world['supplier'].pk}/offers/{live.pk}/"
    terms = {"quota_qty": 250, "order_lead_days": 14, "valid_until": str(timezone.localdate() + timedelta(days=30))}
    assert send(world, "manager", "patch", path, terms).status_code == 403
    assert send(world, "accountant", "patch", path, terms).status_code == 403
    done = send(world, "engineer", "patch", path, terms)  # supply.manage есть, цен нет
    assert done.status_code == 200 and done.json()["quota_qty"] == 250 and done.json()["price"] is None
    refused = send(world, "engineer", "patch", path, {"price": {"amount": "1.00", "currency": "USD"}})
    assert refused.status_code == 403 and refused.json() == {"detail": "SUPPLIER_PRICES_REQUIRED"}
    live.refresh_from_db()
    assert str(live.base_price) == "12.50" and live.stock_quantity == 250
    priced = send(world, "supply", "patch", path, {"price": {"amount": "13.75", "currency": "UZS"}})
    assert priced.status_code == 200 and priced.json()["price"] == {"amount": "13.75", "currency": "UZS"}


@pytest.mark.parametrize(
    "body, code",
    [
        ({"quota_qty": -1}, None),
        ({"valid_from": "2030-02-01", "valid_until": "2030-01-01"}, "OFFER_VALIDITY_RANGE_INVALID"),
        ({"price": {"amount": "-1", "currency": "USD"}}, "OFFER_PRICE_INVALID"),
        ({"price": {"amount": "1", "currency": "XXX"}}, "OFFER_CURRENCY_INVALID"),
        ({"stock_status": "NOPE"}, "STOCK_STATUS_NOT_FOUND"),
    ],
)
def test_offer_edit_refusals(world, body, code):
    path = f"catalog/suppliers/{world['supplier'].pk}/offers/{world['offers']['live'].pk}/"
    response = send(world, "supply", "patch", path, body)
    assert response.status_code == 400
    if code:
        assert response.json() == {"detail": code}


def test_offer_of_another_supplier_is_not_found(world):
    other = send(
        world,
        "supply",
        "patch",
        f"catalog/suppliers/{world['own'].pk}/offers/{world['offers']['live'].pk}/",
        {"quota_qty": 1},
    )
    assert other.status_code == 404


# --- бригады -----------------------------------------------------------------------------------------------------


def test_brigade_rate_is_cut_by_erp_for_roles_without_the_right(world):
    Brigade.objects.create(
        name="Бригада монтажа №1", specialization="Монтаж", headcount=4, rate="800000", currency=world["uzs"]
    )
    for who in ("manager", "accountant", "viewer"):
        row = get(world, who, "catalog/brigades/").json()["results"][0]
        assert row["rate"] is None and row["rate_visible"] is False, who
        assert row["name"] == "Бригада монтажа №1" and row["headcount"] == 4
        assert b"800000" not in json.dumps(row).encode()
    for who in ("supply", "director"):  # cost_margin
        row = get(world, who, "catalog/brigades/").json()["results"][0]
        assert row["rate"] == {"amount": "800000.00", "currency": "UZS", "unit": "day"} and row["rate_visible"] is True


@zone_services
def test_services_zone_holder_sees_and_edits_the_crew_rate(world):
    brigade = Brigade.objects.create(name="ПНР-группа", rate="1200000", currency=world["uzs"])
    row = get(world, "engineer", "catalog/brigades/").json()["results"][0]
    assert row["rate"]["amount"] == "1200000.00"
    done = send(
        world,
        "engineer",
        "patch",
        f"catalog/brigades/{brigade.pk}/",
        {"rate": {"amount": "1300000", "currency": "UZS"}},
    )
    assert done.status_code == 200 and done.json()["rate"]["amount"] == "1300000.00"


def test_engineer_without_zone_cannot_read_or_write_the_rate(world, monkeypatch):
    """Права гл. инженера без зоны услуг и без cost_margin: бригады видны, ставка — нет (и не принимается)."""
    from catalog.tests.desk_world import make_staff

    user = make_staff(world["own"], "viewer", permissions=["catalog.manage", "supply.manage"], label="no-zone")
    from catalog.tests.desk_world import client_for

    client = client_for(user)
    brigade = Brigade.objects.create(name="Бригада", rate="500", currency=world["uzs"])
    assert client.get("/api/v1/catalog/brigades/").json()["results"][0]["rate"] is None
    refused = client.patch(
        f"/api/v1/catalog/brigades/{brigade.pk}/", {"rate": {"amount": "1", "currency": "UZS"}}, format="json"
    )
    assert refused.status_code == 403 and refused.json() == {"detail": "CREW_RATES_REQUIRED"}
    assert (
        client.patch(f"/api/v1/catalog/brigades/{brigade.pk}/", {"specialization": "Монтаж"}, format="json").status_code
        == 200
    )
    brigade.refresh_from_db()
    assert str(brigade.rate) == "500.00"


def test_brigade_create_edit_and_deactivate(world):
    body = {
        "name": "Бригада ПНР",
        "kind": "brigade",
        "headcount": 3,
        "specialization": "ПНР",
        "rate": {"amount": "900000", "currency": "UZS"},
    }
    assert send(world, "manager", "post", "catalog/brigades/", body).status_code == 403
    created = send(world, "supply", "post", "catalog/brigades/", body)
    assert created.status_code == 201 and created.json()["rate"]["amount"] == "900000.00"
    pk = created.json()["id"]
    assert send(world, "supply", "patch", f"catalog/brigades/{pk}/", {"is_active": False}).json()["is_active"] is False
    assert get(world, "supply", "catalog/brigades/").json()["count"] == 0
    assert get(world, "supply", "catalog/brigades/", include_inactive="1").json()["count"] == 1
    assert send(world, "supply", "post", "catalog/brigades/", {"name": "  "}).json() == {
        "detail": "BRIGADE_NAME_REQUIRED"
    }
    assert send(world, "supply", "post", "catalog/brigades/", {"name": "Б", "headcount": 0}).status_code == 400


# --- техдокументация ---------------------------------------------------------------------------------------------


def upload(world, who, name="tz.pdf", content=PDF, content_type="application/pdf", **fields):
    file = SimpleUploadedFile(name, content, content_type=content_type)
    return world["clients"][who].post("/api/v1/catalog/tech-docs/", {"file": file, **fields}, format="multipart")


def test_tech_doc_upload_registers_file_with_product_link_and_streams_it_back(world):
    created = upload(world, "engineer", title="ТЗ на реле", kind="tz", product_id=world["relay"].pk)
    assert created.status_code == 201
    doc = created.json()
    assert (
        doc["kind"] == "tz"
        and doc["previewable"] is True
        and doc["product"]["name"] == "Реле защиты РЗ-1"
        and doc["deal"] is None
    )
    assert doc["original_name"] == "tz.pdf" and doc["size_bytes"] == len(PDF)
    for who in ("manager", "accountant"):
        streamed = world["clients"][who].get(f"/api/v1/catalog/tech-docs/{doc['id']}/file/")
        assert streamed.status_code == 200 and streamed["Content-Type"] == "application/pdf"
        assert streamed["Content-Disposition"].startswith("inline") and streamed["X-Content-Type-Options"] == "nosniff"
        assert b"".join(streamed.streaming_content) == PDF
    forced = world["clients"]["manager"].get(f"/api/v1/catalog/tech-docs/{doc['id']}/file/", {"download": "1"})
    assert forced["Content-Disposition"].startswith("attachment")
    listed = get(world, "manager", "catalog/tech-docs/", product=world["relay"].pk).json()
    assert [r["id"] for r in listed["results"]] == [doc["id"]]
    assert get(world, "manager", "catalog/tech-docs/", kind="drawing").json()["count"] == 0
    card = get(world, "manager", f"catalog/items/{world['relay'].pk}/").json()
    assert [d["title"] for d in card["tech_docs"]] == ["ТЗ на реле"] and card["docs_count"] == 1


def test_tech_doc_binds_to_a_deal(world):
    from sales.models import Deal

    deal = Deal.objects.create(company=world["supplier"], title="Поставка кабеля")
    created = upload(
        world,
        "engineer",
        name="plan.png",
        content=b"\x89PNG\r\n\x1a\n0000",
        content_type="image/png",
        kind="drawing",
        deal_id=deal.pk,
    )
    assert (
        created.status_code == 201
        and created.json()["deal"]["client"] == "ООО Поставщик Север"
        and created.json()["deal"]["id"] == deal.pk
        and created.json()["previewable"] is True
    )
    assert get(world, "manager", "catalog/tech-docs/", deal=deal.pk).json()["count"] == 1


@pytest.mark.parametrize(
    "kwargs, code",
    [
        ({}, "TECH_DOC_LINK_REQUIRED"),
        ({"product_id": 987654}, "PRODUCT_NOT_FOUND"),
        ({"deal_id": 987654}, "DEAL_NOT_FOUND"),
        ({"kind": "poster", "product_id": "__p__"}, "TECH_DOC_KIND_INVALID"),
    ],
)
def test_tech_doc_link_and_kind_are_checked(world, kwargs, code):
    kwargs = {k: (world["relay"].pk if v == "__p__" else v) for k, v in kwargs.items()}
    response = upload(world, "supply", **kwargs)
    assert response.status_code == 400 and response.json() == {"detail": code}
    assert TechDocument.objects.count() == 0


def test_tech_doc_file_checks_size_type_and_content(world, monkeypatch):
    link = {"product_id": world["relay"].pk}
    assert upload(
        world, "supply", name="virus.exe", content=b"MZ", content_type="application/octet-stream", **link
    ).json() == {"detail": "FILE_TYPE_NOT_ALLOWED"}
    assert upload(world, "supply", name="fake.pdf", content=b"not a pdf at all", **link).json() == {
        "detail": "FILE_CONTENT_MISMATCH"
    }
    monkeypatch.setattr(tech_docs, "TECH_DOC_MAX_SIZE", 10)
    # validator читает предел из модуля при каждом вызове
    assert upload(world, "supply", **link).json() == {"detail": "FILE_TOO_LARGE"}
    assert world["clients"]["supply"].post(
        "/api/v1/catalog/tech-docs/", {"product_id": world["relay"].pk}, format="multipart"
    ).json() == {"detail": "NO_FILE_PROVIDED"}
    assert TechDocument.objects.count() == 0


def test_tech_doc_upload_and_delete_need_catalog_manage(world):
    link = {"product_id": world["relay"].pk}
    for who in ("manager", "accountant", "viewer"):
        refused = upload(world, who, **link)
        assert refused.status_code == 403 and refused.json() == {"detail": "ROLE_NOT_PERMITTED"}, who
    doc = upload(world, "supply", **link).json()
    for who in ("manager", "accountant"):
        assert world["clients"][who].delete(f"/api/v1/catalog/tech-docs/{doc['id']}/").status_code == 403
    stored = TechDocument.objects.get(pk=doc["id"])
    name, storage = stored.file.name, stored.file.storage
    assert storage.exists(name)
    assert world["clients"]["supply"].delete(f"/api/v1/catalog/tech-docs/{doc['id']}/").status_code == 204
    assert not TechDocument.objects.filter(pk=doc["id"]).exists() and not storage.exists(name)
    assert get(world, "manager", f"catalog/tech-docs/{doc['id']}/file/").status_code == 404


def test_tech_doc_office_file_is_not_previewable_and_downloads(world):
    docx = b"PK\x03\x04" + b"0" * 40
    created = upload(
        world,
        "supply",
        name="reg.docx",
        content=docx,
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        kind="pnr",
        product_id=world["relay"].pk,
    )
    assert created.status_code == 201 and created.json()["previewable"] is False
    streamed = get(world, "manager", f"catalog/tech-docs/{created.json()['id']}/file/")
    assert streamed["Content-Disposition"].startswith("attachment")


# --- справочники -------------------------------------------------------------------------------------------------


def test_hs_codes_list_search_and_create(world):
    body = {"code": "8536", "name": "Аппаратура для коммутации", "unit_name": "кг"}
    assert send(world, "manager", "post", "master-data/hs-codes/", body).status_code == 403
    group = send(world, "supply", "post", "master-data/hs-codes/", {"code": "85", "name": "Электрические машины"})
    assert group.status_code == 201 and group.json()["level"] == 2
    created = send(world, "supply", "post", "master-data/hs-codes/", body)
    assert created.status_code == 201 and created.json()["level"] == 4 and created.json()["is_active"] is True
    assert HSCode.objects.get(code="8536").parent.code == "85"
    assert send(world, "supply", "post", "master-data/hs-codes/", body).json() == {"detail": "HS_CODE_EXISTS"}
    assert send(world, "supply", "post", "master-data/hs-codes/", {"code": "853", "name": "x"}).json() == {
        "detail": "HS_CODE_INVALID"
    }
    assert send(world, "supply", "post", "master-data/hs-codes/", {"code": "8537", "name": " "}).json() == {
        "detail": "HS_NAME_REQUIRED"
    }
    found = get(world, "manager", "master-data/hs-codes/", q="коммутации").json()
    assert [r["code"] for r in found["results"]] == ["8536"]
    assert [r["code"] for r in get(world, "manager", "master-data/hs-codes/", level=2).json()["results"]] == ["85"]
    assert [r["code"] for r in get(world, "manager", "master-data/hs-codes/", q="85").json()["results"]] == [
        "85",
        "8536",
    ]


def test_hs_code_edit_closes_with_a_date_and_never_changes_the_code(world):
    code = HSCode.objects.create(code="8544", name="Провода", level=4)
    path = f"master-data/hs-codes/{code.pk}/"
    assert send(world, "manager", "patch", path, {"name": "x"}).status_code == 403
    yesterday = str(timezone.localdate() - timedelta(days=1))
    done = send(world, "supply", "patch", path, {"name": "Провода и кабели", "valid_until": yesterday, "code": "9999"})
    assert done.status_code == 200 and done.json()["code"] == "8544" and done.json()["is_active"] is False
    assert [r["code"] for r in get(world, "manager", "master-data/hs-codes/", active="1").json()["results"]] == []
    bad = send(world, "supply", "patch", path, {"valid_from": "2030-01-01"})
    assert bad.json() == {"detail": "HS_VALIDITY_RANGE_INVALID"}


def test_manufacturers_are_writable_with_catalog_manage_only(world):
    from rest_framework.test import APIClient

    assert (
        APIClient().get("/api/v1/catalog/manufacturers/").status_code == 200
    )  # выбор бренда в карточке остаётся открытым
    assert APIClient().post("/api/v1/catalog/manufacturers/", {"name": "Brand"}, format="json").status_code == 401
    assert send(world, "manager", "post", "catalog/manufacturers/", {"name": "Brand"}).status_code == 403
    created = send(
        world, "supply", "post", "catalog/manufacturers/", {"name": "Siemens-Test", "website": "https://example.test"}
    )
    assert created.status_code == 201 and created.json()["is_active"] is True
    assert send(world, "supply", "post", "catalog/manufacturers/", {"name": "siemens-test"}).json() == {
        "detail": "MANUFACTURER_EXISTS"
    }
    pk = created.json()["id"]
    assert send(world, "manager", "patch", f"catalog/manufacturers/{pk}/", {"is_active": False}).status_code == 403
    assert (
        send(world, "supply", "patch", f"catalog/manufacturers/{pk}/", {"is_active": False}).json()["is_active"]
        is False
    )
    assert Manufacturer.objects.get(pk=pk).is_active is False
    assert get(world, "manager", "catalog/manufacturers/").json() in (
        [],
        {"count": 0, "next": None, "previous": None, "results": []},
    ) or all(m["id"] != pk for m in _results(get(world, "manager", "catalog/manufacturers/").json()))
    hidden = _results(get(world, "manager", "catalog/manufacturers/", include_inactive="1").json())
    assert all(m["id"] != pk for m in hidden)  # менеджер не может включить показ отключённых
    shown = _results(get(world, "supply", "catalog/manufacturers/", include_inactive="1").json())
    assert any(m["id"] == pk for m in shown)
    assert send(world, "supply", "delete", f"catalog/manufacturers/{pk}/").status_code == 405


def _results(payload):
    return payload["results"] if isinstance(payload, dict) else payload


def test_exchange_rate_rows_are_readable_by_staff(world):
    today = timezone.localdate()
    ExchangeRate.objects.create(currency=world["usd"], rate_to_uzs="12650.5", rate_date=today, source="CBU")
    ExchangeRate.objects.create(
        currency=world["usd"], rate_to_uzs="12600", rate_date=today - timedelta(days=1), source="MANUAL"
    )
    rows = get(world, "manager", "exchange-rates/").json()
    assert [r["rate_to_uzs"] for r in rows["results"]] == ["12650.5", "12600"]
    assert rows["results"][1]["source"] == "MANUAL"
    assert get(world, "accountant", "exchange-rates/", currency="eur").json()["count"] == 0
    from rest_framework.test import APIClient

    assert APIClient().get("/api/v1/exchange-rates/").status_code == 401
    # ввод курса остаётся за settings.edit
    assert (
        send(
            world,
            "supply",
            "post",
            "exchange-rates/manual/",
            {"currency": "USD", "rate_date": str(today), "rate_to_uzs": "1"},
        ).status_code
        == 403
    )


# --- ревью #299: журнал правок, заголовки файла, устойчивость удаления -----------------------------------------------


def _log(event_code):
    from crm.models import ActivityLog

    return list(ActivityLog.objects.filter(event_code=event_code).order_by("id"))


def test_offer_edit_is_written_to_the_audit_log_with_before_and_after(world):
    live = world["offers"]["live"]
    path = f"catalog/suppliers/{world['supplier'].pk}/offers/{live.pk}/"
    assert (
        send(
            world, "supply", "patch", path, {"quota_qty": 250, "price": {"amount": "13.75", "currency": "UZS"}}
        ).status_code
        == 200
    )
    (entry,) = _log("admin.supplier_offer.updated")
    assert entry.user == world["users"]["supply"] and entry.entity_id == live.pk
    assert entry.before_data["stock_quantity"] == 500 and entry.after_data["stock_quantity"] == 250
    assert (entry.before_data["base_price"], entry.after_data["base_price"]) == ("12.50", "13.75")
    assert entry.after_data["currency"] == "UZS"
    # правка без изменений следа не оставляет
    send(world, "supply", "patch", path, {"quota_qty": 250})
    assert len(_log("admin.supplier_offer.updated")) == 1


def test_brigade_hs_code_manufacturer_and_file_deletion_are_audited(world):
    created = send(
        world, "supply", "post", "catalog/brigades/", {"name": "Б", "rate": {"amount": "100", "currency": "UZS"}}
    ).json()
    send(world, "supply", "patch", f"catalog/brigades/{created['id']}/", {"rate": {"amount": "200", "currency": "UZS"}})
    (made, changed) = _log("admin.brigade.created"), _log("admin.brigade.updated")
    assert (
        made[0].after_data["rate"] == "100.00"
        and changed[0].before_data["rate"] == "100.00"
        and changed[0].after_data["rate"] == "200.00"
    )
    code = send(world, "supply", "post", "master-data/hs-codes/", {"code": "8536", "name": "x"}).json()
    send(world, "supply", "patch", f"master-data/hs-codes/{code['id']}/", {"valid_until": "2020-01-01"})
    assert _log("admin.hs_code.created") and _log("admin.hs_code.updated")[0].after_data["valid_until"] == "2020-01-01"
    brand = send(world, "supply", "post", "catalog/manufacturers/", {"name": "Brand-A"}).json()
    send(world, "supply", "patch", f"catalog/manufacturers/{brand['id']}/", {"is_active": False})
    assert _log("admin.manufacturer.created") and _log("admin.manufacturer.updated")[0].before_data["is_active"] is True
    doc = upload(world, "supply", product_id=world["relay"].pk).json()
    assert world["clients"]["supply"].delete(f"/api/v1/catalog/tech-docs/{doc['id']}/").status_code == 204
    (deleted,) = _log("admin.tech_doc.deleted")
    assert deleted.level == "WARNING" and deleted.before_data["original_name"] == "tz.pdf"


def test_tech_doc_file_is_served_under_a_sandbox_csp(world):
    doc = upload(world, "supply", product_id=world["relay"].pk).json()
    response = get(world, "manager", f"catalog/tech-docs/{doc['id']}/file/")
    assert response["Content-Security-Policy"] == "default-src 'none'; sandbox"


def test_deleting_a_doc_survives_a_storage_failure(world, monkeypatch):
    doc = upload(world, "supply", product_id=world["relay"].pk).json()
    from django.core.files.storage import FileSystemStorage

    def broken(self, name):
        raise OSError("down")

    monkeypatch.setattr(FileSystemStorage, "delete", broken)
    assert world["clients"]["supply"].delete(f"/api/v1/catalog/tech-docs/{doc['id']}/").status_code == 204
    assert not TechDocument.objects.filter(pk=doc["id"]).exists()


def test_item_card_reports_the_full_number_of_files(world):
    for _ in range(22):
        TechDocument.objects.create(kind="other", title="t", file="x", original_name="x.pdf", product=world["relay"])
    card = get(world, "manager", f"catalog/items/{world['relay'].pk}/").json()
    assert len(card["tech_docs"]) == 20 and card["docs_count"] == 22
    listed = {r["id"]: r for r in get(world, "manager", "catalog/items/", page_size=50).json()["results"]}
    assert listed[world["relay"].pk]["docs_count"] == 22
