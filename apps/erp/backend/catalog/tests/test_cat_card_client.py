"""CAT-CARD-2 «Карточка товара в кабинете клиента»: изготовитель, страна, артикул изготовителя, гарантия, документы.

Что видит клиент — только то, что собирает `catalog.published.project()` белым списком; документы — только в детальной
карточке и только «видно клиенту» + действующие (как «Сертификаты номенклатуры» в 1С: на печать идут действующие).
Файл документа — потоком через портал, одинаковый 404 для скрытого, просроченного, чужого и несуществующего.
Поставщик клиенту не виден ни в карточке, ни в имени файла (ORCHESTRATOR §3.5).
"""

import datetime
from urllib.parse import unquote

import pytest
from django.core.files.base import ContentFile
from django.utils import timezone
from parties.models import CompanySettings
from portal.tests.conftest import client_contact, client_session, client_type, portal_client  # noqa: F401, E402

# Миры и фикстуры опубликованного слоя (они же собирают сессию портала клиента).
from catalog.constants import MODE_CLIENT, MODE_LEAD
from catalog.models import DocumentKind, Manufacturer, ProductImage, ProductStatus, TechDocument
from catalog.published import project, published_products
from catalog.tests.test_published_layer import (  # noqa: F401
    SENTINELS,
    SUPPLIER_NAME,
    SUPPLIER_SKU,
    assert_no_internal_layer,
    client_company,
    make_card,
    world,
)
from core.models import Country

pytestmark = pytest.mark.django_db

API = "/api/portal/v1"
PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
DAY = datetime.timedelta(days=1)


def today():
    """«Сегодня» по `TIME_ZONE` (Asia/Tashkent) — как правило видимости документов; не в момент импорта модуля."""
    return timezone.localdate()


# Мир опубликованного слоя и сессия портала — фикстуры `test_published_layer` и `portal/tests/conftest`; здесь они под своими
# именами, чтобы импорт не «переопределялся» параметрами тестов (F811).


@pytest.fixture
def card_world(request):
    return request.getfixturevalue("world")


@pytest.fixture
def portal(request):
    return request.getfixturevalue("portal_client")


@pytest.fixture
def portal_contact(request):
    return request.getfixturevalue("client_contact")


@pytest.fixture
def portal_session(request):
    return request.getfixturevalue("client_session")


def country(code, name):
    return Country.objects.get_or_create(code=code, defaults={"name": name, "alpha2": code})[0]


def document(
    product,
    *,
    title="Сертификат соответствия",
    kind="certificate",
    visible=True,
    valid_until=None,
    stored_name="scan.pdf",
    content=PDF,
    **fields,
):
    DocumentKind.objects.get_or_create(code=kind, defaults={"name": f"Вид {kind}", "has_validity": True})
    fields.setdefault("original_name", "scan.pdf")
    fields.setdefault("content_type", "application/pdf")
    doc = TechDocument(
        kind=kind, title=title, client_visible=visible, valid_until=valid_until, product=product, **fields
    )
    doc.file.save(stored_name, ContentFile(content), save=False)
    doc.size_bytes = len(content)
    doc.save()
    return doc


def detail(client, product):
    return client.get(f"{API}/catalog/{product.pk}")


def file_url(product, doc):
    return f"{API}/catalog/{product.pk}/documents/{doc.pk}/file"


@pytest.fixture
def certified(card_world):
    """Опубликованная карточка с изготовителем, страной, артикулом, гарантией и документами."""
    germany = country("DE", "Германия")
    brand = Manufacturer.objects.create(name="Beispiel GmbH", country=germany)
    product = make_card(
        card_world,
        brand=brand,
        manufacturer_part_number="BX-6205-2RS",
        warranty_months=18,
        warranty_terms="Гарантия на заводской брак",
    )
    return product


# ── 1. Проекция: изготовитель, страна, артикул, гарантия ────────────────────────────────────────────────


def test_projection_carries_manufacturer_part_number_country_and_warranty(certified):
    item = project(certified, mode=MODE_CLIENT)

    assert item["manufacturer"] == {"name": "Beispiel GmbH", "country": "Германия"}
    assert item["manufacturer_part_number"] == "BX-6205-2RS"
    assert item["country_of_origin"] == "Германия", "своей страны у карточки нет — страна бренда"
    assert item["warranty"] == {"months": 18, "terms": "Гарантия на заводской брак"}
    assert "documents" not in item, "документы — только в детальной карточке портала"
    assert_no_internal_layer(item, "project(client)")


def test_detail_projection_has_every_contract_key(certified):
    from catalog.published import CATALOG_ITEM_KEYS

    assert set(project(certified, mode=MODE_CLIENT, with_documents=True)) == CATALOG_ITEM_KEYS


def test_projection_without_data_has_nulls(card_world):
    item = project(make_card(card_world), mode=MODE_CLIENT)
    assert item["manufacturer"] is None
    assert item["manufacturer_part_number"] is None
    assert item["country_of_origin"] is None
    assert item["warranty"] is None


def test_lead_projection_has_the_manufacturer_block_but_no_documents(certified):
    item = project(certified, mode=MODE_LEAD)
    assert item["manufacturer"]["name"] == "Beispiel GmbH" and item["manufacturer_part_number"] == "BX-6205-2RS"
    assert "documents" not in item and "price" not in item


def test_own_country_of_origin_beats_brand_country(certified):
    certified.country_of_origin = country("CN", "Китай")
    certified.save()
    item = project(certified, mode=MODE_CLIENT)
    assert item["country_of_origin"] == "Китай"
    assert item["manufacturer"]["country"] == "Германия", "страна изготовителя — отдельно от страны происхождения"


def test_brand_without_country_and_card_without_origin(card_world):
    brand = Manufacturer.objects.create(name="NoCountry Ltd")
    item = project(make_card(card_world, brand=brand), mode=MODE_CLIENT)
    assert item["manufacturer"] == {"name": "NoCountry Ltd", "country": None}
    assert item["country_of_origin"] is None


def test_warranty_falls_back_to_company_default_and_item_wins(card_world):
    CompanySettings.objects.update_or_create(company=card_world["own"], defaults={"default_warranty_months": 24})
    plain = make_card(card_world, name="Без своей гарантии")
    assert project(plain, mode=MODE_CLIENT)["warranty"] == {"months": 24, "terms": ""}
    own = make_card(card_world, name="Со своей", warranty_months=6, warranty_terms="Шесть месяцев")
    assert project(own, mode=MODE_CLIENT)["warranty"] == {"months": 6, "terms": "Шесть месяцев"}
    none = make_card(card_world, name="Без гарантии", warranty_months=0)
    assert (
        project(none, mode=MODE_CLIENT)["warranty"] is None
    ), "0 месяцев — явное «без гарантии», срок компании не подставляется"


def test_project_many_does_not_query_per_card(card_world, django_assert_max_num_queries):
    germany = country("DE", "Германия")
    brand = Manufacturer.objects.create(name="Beispiel GmbH", country=germany)
    for n in range(5):
        make_card(card_world, name=f"Карточка {n}", brand=brand, country_of_origin=germany)
    from catalog.published import project_many

    with django_assert_max_num_queries(8):
        items = project_many(published_products(), mode=MODE_CLIENT)
    assert len(items) == 5 and all(item["manufacturer"] for item in items)


# ── 2. Портал: карточка, список, документы ──────────────────────────────────────────────────────────────


def test_detail_shows_only_visible_and_valid_documents(certified, portal):
    shown = document(certified, title="Сертификат ТР", number="РОСС RU.0001", issued_by="Орган по сертификации")
    shown.issued_at = today() - 30 * DAY
    shown.valid_until = today() + 30 * DAY
    shown.save()
    forever = document(certified, title="Паспорт изделия", kind="passport", number="", valid_until=None)
    last_day = document(certified, title="Декларация (последний день)", kind="declaration", valid_until=today())
    document(certified, title="Скрытый", visible=False)
    document(certified, title="Просроченный", valid_until=today() - DAY)

    body = detail(portal, certified).json()

    assert {d["id"] for d in body["documents"]} == {shown.pk, forever.pk, last_day.pk}
    row = next(d for d in body["documents"] if d["id"] == shown.pk)
    assert row == {
        "id": shown.pk,
        "kind_name": DocumentKind.objects.get(code="certificate").name,
        "title": "Сертификат ТР",
        "number": "РОСС RU.0001",
        "issued_by": "Орган по сертификации",
        "issued_at": (today() - 30 * DAY).isoformat(),
        "valid_until": (today() + 30 * DAY).isoformat(),
    }
    assert next(d for d in body["documents"] if d["id"] == forever.pk)["valid_until"] is None


def test_detail_does_not_show_documents_of_other_cards_or_deals(certified, card_world, portal):
    other = make_card(card_world, name="Другая карточка")
    document(other, title="Чужой сертификат")
    TechDocument.objects.create(
        kind="other", title="Проектный документ", client_visible=True, file=ContentFile(PDF, name="p.pdf")
    )
    assert detail(portal, certified).json()["documents"] == []


def test_detail_payload_has_the_new_fields_and_no_internal_layer(certified, portal):
    document(certified, original_name=f"{SUPPLIER_NAME}_{SUPPLIER_SKU}.pdf", number="N-1")
    ProductImage.objects.create(product=certified, image_url="/media/catalog/b.jpg")
    ProductImage.objects.create(product=certified, image_url="/media/catalog/a.jpg", is_main=True)

    response = detail(portal, certified)

    assert response.status_code == 200
    body = response.json()
    assert body["manufacturer"] == {"name": "Beispiel GmbH", "country": "Германия"}
    assert body["manufacturer_part_number"] == "BX-6205-2RS"
    assert body["country_of_origin"] == "Германия"
    assert body["warranty"] == {"months": 18, "terms": "Гарантия на заводской брак"}
    assert body["images"][0].endswith("/a.jpg"), "главное фото первым"
    text = response.content.decode()
    for sentinel in SENTINELS:
        assert sentinel not in text
    for key in ("original_name", "file", "size_bytes", "content_type", "client_visible", "product"):
        assert all(key not in d for d in body["documents"]), key


def test_list_has_manufacturer_but_no_documents(certified, portal):
    document(certified)
    items = portal.get(f"{API}/catalog").json()["items"]
    assert items[0]["manufacturer"]["name"] == "Beispiel GmbH"
    assert items[0]["manufacturer_part_number"] == "BX-6205-2RS"
    assert "documents" not in items[0]


# ── 3. Файл документа ───────────────────────────────────────────────────────────────────────────────────


def test_client_downloads_a_valid_visible_document(certified, portal, portal_contact):
    doc = document(certified, title="Сертификат соответствия ТР ТС", number="N-77", original_name="orig.pdf")

    response = portal.get(file_url(certified, doc), REMOTE_ADDR="203.0.113.9")

    assert response.status_code == 200
    assert b"".join(response.streaming_content) == PDF
    assert response["Content-Type"].startswith("application/pdf")
    disposition = unquote(response["Content-Disposition"])
    assert disposition.startswith("attachment;") and "Сертификат_соответствия_ТР_ТС.pdf" in disposition
    assert "orig" not in disposition
    assert response["X-Content-Type-Options"] == "nosniff"
    assert "no-store" in response["Cache-Control"] and "private" in response["Cache-Control"]


def test_file_name_comes_from_title_not_from_the_uploaded_name_with_supplier(certified, portal):
    doc = document(certified, title="Паспорт", kind="passport", original_name=f"{SUPPLIER_NAME}-{SUPPLIER_SKU}.pdf")
    response = portal.get(file_url(certified, doc))
    assert response.status_code == 200
    disposition = unquote(response["Content-Disposition"])
    assert SUPPLIER_NAME not in disposition and SUPPLIER_SKU not in disposition
    assert "Паспорт.pdf" in disposition
    assert_no_internal_layer(dict(response.items()), "заголовки файла")


def test_file_extension_follows_the_stored_file(certified, portal):
    doc = document(certified, title="Скан", original_name="a.jpg", content_type="image/jpeg")
    doc.file.save("scan.jpg", ContentFile(b"\xff\xd8\xff\xe0" + b"0" * 8), save=True)
    response = portal.get(file_url(certified, doc))
    assert response.status_code == 200
    assert response["Content-Type"] == "image/jpeg"
    assert unquote(response["Content-Disposition"]).endswith("Скан.jpg")


def test_every_issue_is_audited(certified, portal, portal_contact, portal_session):
    from crm.models import ActivityLog

    doc = document(certified, number="N-1")
    portal.get(file_url(certified, doc), REMOTE_ADDR="203.0.113.7")
    portal.get(file_url(certified, doc), REMOTE_ADDR="203.0.113.7")

    logs = list(ActivityLog.objects.filter(event_code="document.downloaded_by_client").order_by("id"))
    assert len(logs) == 2
    log = logs[0]
    assert (log.contact_id, log.company_id) == (portal_contact.pk, portal_contact.company_id)
    assert (log.entity_type, log.entity_id, log.deal_id) == ("tech_document", doc.pk, None)
    assert log.event_params == {
        "document_id": doc.pk,
        "kind": "certificate",
        "number": "N-1",
        "product_id": certified.pk,
        "source": "catalog",
        "contact_id": portal_contact.pk,
        "contact_name": portal_contact.name,
        "session_id": portal_session.pk,
        "ip": "203.0.113.7",
    }
    assert SUPPLIER_NAME not in str(log.event_params) + log.detail


NOT_FOUND = {"detail": "NOT_FOUND"}


def _not_found(client, url):
    response = client.get(url)
    assert response.status_code == 404, url
    assert response.json() == NOT_FOUND, "причины не различаются"


def test_hidden_document_is_404(certified, portal):
    _not_found(portal, file_url(certified, document(certified, visible=False)))


def test_expired_document_is_404_and_last_valid_day_is_not(certified, portal):
    _not_found(portal, file_url(certified, document(certified, valid_until=today() - DAY)))
    assert portal.get(file_url(certified, document(certified, valid_until=today()))).status_code == 200


def test_document_of_another_card_is_404(certified, card_world, portal):
    other = make_card(card_world, name="Другая карточка")
    doc = document(other)
    assert portal.get(file_url(other, doc)).status_code == 200, "для своей карточки документ отдаётся"
    _not_found(portal, file_url(certified, doc))


def test_unpublished_card_is_404_even_for_a_visible_document(card_world, portal):
    draft = make_card(card_world, name="Черновик", published=False)
    _not_found(portal, file_url(draft, document(draft)))


def test_archived_card_is_404(certified, portal):
    doc = document(certified)
    certified.status = ProductStatus.objects.get_or_create(code="ARCHIVED", defaults={"name": "Архив"})[0]
    certified.save()
    _not_found(portal, file_url(certified, doc))


def test_unknown_ids_and_documents_without_a_card_are_404(certified, portal):
    _not_found(portal, f"{API}/catalog/{certified.pk}/documents/999999/file")
    _not_found(portal, f"{API}/catalog/999999/documents/1/file")
    orphan = TechDocument.objects.create(
        kind="other", title="Без карточки", client_visible=True, file=ContentFile(PDF, name="o.pdf")
    )
    _not_found(portal, file_url(certified, orphan))


def test_file_lost_in_storage_is_404(certified, portal):
    doc = document(certified)
    doc.file.storage.delete(doc.file.name)
    _not_found(portal, file_url(certified, doc))


def test_negative_requests_leave_no_audit_trail(certified, portal):
    from crm.models import ActivityLog

    portal.get(file_url(certified, document(certified, visible=False)))
    portal.get(file_url(certified, document(certified, valid_until=today() - DAY)))
    assert not ActivityLog.objects.filter(event_code="document.downloaded_by_client").exists()


def test_anonymous_is_401(certified):
    from rest_framework.test import APIClient

    doc = document(certified)
    assert APIClient().get(file_url(certified, doc)).status_code == 401


def test_read_only_contact_can_download(certified, readonly_portal_client):
    assert readonly_portal_client.get(file_url(certified, document(certified))).status_code == 200


@pytest.fixture
def readonly_portal_client(card_world, request):
    request.getfixturevalue("client_company")  # тип CLIENT: компания допущена в кабинет
    from django.conf import settings
    from parties.models import Contact
    from portal.tests.conftest import PortalAPIClient, make_portal_session

    contact = Contact.objects.create(
        company=card_world["client_company"], name="Читатель", email="reader@example.uz", can_act=False, language="ru"
    )
    session = make_portal_session(contact, card_world["client_company"], "magic_link")
    client = PortalAPIClient()
    client.cookies[settings.PORTAL_SESSION_COOKIE_NAME] = session.raw_token
    client.credentials(HTTP_X_PORTAL_SESSION=session.raw_token)
    return client


# ── 4. Граница срока по часовому поясу и враждебные заголовки ───────────────────────────────────────────


@pytest.mark.parametrize(
    ("moment", "valid"),
    [
        ("2026-11-04T18:30:00Z", True),  # 23:30 4 ноября по Ташкенту: «до 4 ноября» ещё действует
        ("2026-11-04T19:30:00Z", False),  # 00:30 5 ноября по Ташкенту: срок вышел (по UTC всё ещё 4-е)
    ],
)
def test_validity_ends_at_midnight_of_the_business_time_zone(certified, portal, monkeypatch, moment, valid):
    doc = document(certified, valid_until=datetime.date(2026, 11, 4))
    # freezegun в образе тестов нет: `timezone.localdate()` берёт момент из `django.utils.timezone.now`, его и подменяем.
    frozen = datetime.datetime.fromisoformat(moment.replace("Z", "+00:00"))
    monkeypatch.setattr("django.utils.timezone.now", lambda: frozen)
    listed = [d["id"] for d in detail(portal, certified).json()["documents"]]
    status = portal.get(file_url(certified, doc)).status_code
    assert (doc.pk in listed) is valid
    assert status == (200 if valid else 404)


def test_content_disposition_survives_a_hostile_title(certified, portal):
    title = 'Серт "A"; filename=evil.exe\r\nX-Injected: 1\r\nSet-Cookie: a=b'
    doc = document(certified, title=title)

    response = portal.get(file_url(certified, doc))

    assert response.status_code == 200
    disposition = response["Content-Disposition"]
    assert disposition.startswith("attachment;") and disposition.count("attachment") == 1
    assert "\r" not in disposition and "\n" not in disposition
    assert "; filename=evil" not in disposition, "кавычки и «;» названия не открывают второй параметр заголовка"
    assert "X-Injected" not in response and "Set-Cookie" not in response
    assert all("\r" not in value and "\n" not in value for _name, value in response.items())


@pytest.mark.parametrize(
    ("stored_name", "content", "content_type"),
    [
        ("x.svg", b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"/>', "image/svg+xml"),
        ("x.html", b"<html><script>alert(1)</script></html>", "text/html"),
    ],
)
def test_active_content_is_an_attachment_in_a_sandbox(certified, portal, stored_name, content, content_type):
    """Файл вносит сотрудник: SVG или HTML не должен исполняться на домене кабинета, даже по прямой ссылке."""
    doc = document(certified, stored_name=stored_name, content=content, content_type=content_type)

    response = portal.get(file_url(certified, doc))

    assert response.status_code == 200
    assert response["Content-Disposition"].startswith("attachment;")
    assert response["X-Content-Type-Options"] == "nosniff"
    assert "sandbox" in response["Content-Security-Policy"]
    assert "default-src 'none'" in response["Content-Security-Policy"]
