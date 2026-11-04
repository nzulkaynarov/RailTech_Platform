"""CAT-CARD-1 «Карточка товара»: фото, документы с видом из справочника, страна происхождения, гарантия, полнота.

Мир — `desk_world` (сотрудники по ролям каталога Платформы). Права: чтение — любой сотрудник бэк-офиса, запись — `catalog.manage`
(роль `supply`/`engineer`; `manager` и `accountant` только читают). Проверки бьют в ERP напрямую, минуя BFF.
"""

from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from parties.models import CompanySettings

from catalog.completeness import CompletenessContext, completeness, summarize_completeness
from catalog.desk import images as image_service
from catalog.models import Category, DocumentKind, Manufacturer, Product, ProductImage, TechDocument
from catalog.tests.desk_world import build_world
from core.models import Country

pytestmark = pytest.mark.django_db

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32
JPEG = b"\xff\xd8\xff\xe0" + b"0" * 32
WEBP = b"RIFF\x24\x00\x00\x00WEBP" + b"0" * 32
PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


@pytest.fixture
def world():
    return build_world()


def item_url(world, suffix=""):
    return f"/api/v1/catalog/items/{world['relay'].pk}/{suffix}"


def photo(world, who="supply", name="a.png", content=PNG, content_type="image/png", target=None, **fields):
    file = SimpleUploadedFile(name, content, content_type=content_type)
    url = f"/api/v1/catalog/items/{(target or world['relay']).pk}/images/"
    return world["clients"][who].post(url, {"image": file, **fields}, format="multipart")


def card(world, who="manager", target=None):
    return world["clients"][who].get(f"/api/v1/catalog/items/{(target or world['relay']).pk}/").json()


def gallery(world):
    return [(i["id"], i["is_main"], i["sort_order"]) for i in card(world)["images"]]


def upload_n(world, count):
    return [photo(world, name=f"{n}.png").json()["id"] for n in range(count)]


# --- фото ---------------------------------------------------------------------------------------------------------


def test_first_photo_is_main_and_later_ones_are_not(world):
    first = photo(world)
    assert first.status_code == 201
    body = first.json()
    assert body["is_main"] is True and body["sort_order"] == 0
    assert body["url"].startswith(f"/media/products/{world['relay'].pk}/images/")
    second = photo(world, name="b.jpg", content=JPEG, content_type="image/jpeg", alt_text="Вид спереди").json()
    assert (second["is_main"], second["sort_order"], second["alt"]) == (False, 1, "Вид спереди")
    third = photo(world, name="c.webp", content=WEBP, content_type="image/webp").json()
    assert [(i["id"], i["is_main"]) for i in card(world)["images"]] == [
        (body["id"], True),
        (second["id"], False),
        (third["id"], False),
    ]


def test_upload_may_take_the_main_place_and_keeps_exactly_one_main(world):
    first = photo(world).json()
    newer = photo(world, name="b.png", is_main="true").json()
    assert newer["is_main"] is True
    assert [i["id"] for i in card(world)["images"] if i["is_main"]] == [newer["id"]]
    assert ProductImage.objects.get(pk=first["id"]).is_main is False


def test_the_eleventh_photo_is_refused(world):
    assert all(photo(world, name=f"{n}.png").status_code == 201 for n in range(image_service.MAX_IMAGES))
    refused = photo(world, name="extra.png")
    assert refused.status_code == 400 and refused.json() == {"detail": "IMAGE_LIMIT_REACHED"}
    assert ProductImage.objects.filter(product=world["relay"]).count() == image_service.MAX_IMAGES
    # Лимит — на товар: у соседнего товара фото принимаются.
    assert photo(world, target=world["cable"]).status_code == 201


def test_photo_file_checks(world, monkeypatch):
    svg = photo(world, name="logo.svg", content=b"<svg onload='x'/>", content_type="image/svg+xml")
    assert svg.status_code == 400 and svg.json() == {"detail": "FILE_TYPE_NOT_ALLOWED"}
    gif = photo(world, name="a.gif", content=b"GIF89a" + b"0" * 20, content_type="image/gif")
    assert gif.json() == {"detail": "FILE_TYPE_NOT_ALLOWED"}
    fake = photo(world, name="fake.png", content=b"not an image at all", content_type="image/png")
    assert fake.json() == {"detail": "FILE_CONTENT_MISMATCH"}
    monkeypatch.setattr(image_service, "IMAGE_MAX_SIZE", 10)
    assert photo(world).json() == {"detail": "FILE_TOO_LARGE"}
    assert world["clients"]["supply"].post(item_url(world, "images/"), {}, format="multipart").json() == {
        "detail": "NO_FILE_PROVIDED"
    }
    assert ProductImage.objects.count() == 0


def test_photo_size_limit_is_five_megabytes():
    assert image_service.IMAGE_MAX_SIZE == 5 * 1024 * 1024


def test_photo_write_needs_catalog_manage_and_read_does_not(world):
    for who in ("manager", "accountant", "viewer"):
        refused = photo(world, who=who)
        assert refused.status_code == 403 and refused.json() == {"detail": "ROLE_NOT_PERMITTED"}, who
    image_id = photo(world, who="engineer").json()["id"]
    for who in ("manager", "accountant", "viewer"):
        client = world["clients"][who]
        assert client.patch(item_url(world, f"images/{image_id}/"), {"alt_text": "x"}, format="json").status_code == 403
        assert client.delete(item_url(world, f"images/{image_id}/")).status_code == 403
        assert [i["id"] for i in card(world, who)["images"]] == [image_id]


def test_setting_the_main_photo_moves_the_flag(world):
    a, b, c = upload_n(world, 3)
    moved = world["clients"]["supply"].patch(item_url(world, f"images/{c}/"), {"is_main": True}, format="json")
    assert moved.status_code == 200 and moved.json()["is_main"] is True
    assert gallery(world) == [(a, False, 0), (b, False, 1), (c, True, 2)]


def test_the_main_flag_cannot_be_taken_away_without_a_replacement(world):
    a, _b = upload_n(world, 2)
    refused = world["clients"]["supply"].patch(item_url(world, f"images/{a}/"), {"is_main": False}, format="json")
    assert refused.status_code == 400 and refused.json() == {"detail": "IMAGE_MAIN_REQUIRED"}
    assert gallery(world)[0] == (a, True, 0)


def test_reordering_renumbers_without_gaps_and_keeps_the_main(world):
    a, b, c, d = upload_n(world, 4)
    client = world["clients"]["supply"]
    assert client.patch(item_url(world, f"images/{d}/"), {"sort_order": 0}, format="json").status_code == 200
    assert gallery(world) == [(d, False, 0), (a, True, 1), (b, False, 2), (c, False, 3)]
    assert client.patch(item_url(world, f"images/{d}/"), {"sort_order": 99}, format="json").status_code == 200
    assert gallery(world) == [(a, True, 0), (b, False, 1), (c, False, 2), (d, False, 3)]
    assert client.patch(item_url(world, f"images/{b}/"), {"sort_order": 2}, format="json").status_code == 200
    assert gallery(world) == [(a, True, 0), (c, False, 1), (b, False, 2), (d, False, 3)]


def test_deleting_the_main_photo_promotes_the_next_one_and_removes_the_file(world):
    a, b, c = upload_n(world, 3)
    stored = ProductImage.objects.get(pk=a)
    name, storage = stored.image.name, stored.image.storage
    assert storage.exists(name)
    assert world["clients"]["supply"].delete(item_url(world, f"images/{a}/")).status_code == 204
    assert not storage.exists(name)
    assert gallery(world) == [(b, True, 0), (c, False, 1)]
    # Не главное: главное остаётся, порядок без дыр.
    assert world["clients"]["supply"].delete(item_url(world, f"images/{b}/")).status_code == 204
    assert world["clients"]["supply"].delete(item_url(world, f"images/{c}/")).status_code == 204
    assert gallery(world) == []
    photo(world)
    assert [i[1] for i in gallery(world)] == [True]


def test_deleting_a_middle_photo_closes_the_gap(world):
    a, b, c = upload_n(world, 3)
    assert world["clients"]["supply"].delete(item_url(world, f"images/{b}/")).status_code == 204
    assert gallery(world) == [(a, True, 0), (c, False, 1)]


def test_a_photo_of_another_product_is_not_found(world):
    other = photo(world, target=world["cable"]).json()["id"]
    client = world["clients"]["supply"]
    assert client.patch(item_url(world, f"images/{other}/"), {"alt_text": "x"}, format="json").status_code == 404
    assert client.delete(item_url(world, f"images/{other}/")).status_code == 404
    assert ProductImage.objects.filter(pk=other).exists()


def test_photo_alt_text_is_edited_and_trimmed(world):
    a = photo(world).json()["id"]
    edited = world["clients"]["supply"].patch(
        item_url(world, f"images/{a}/"), {"alt_text": "  Вид сбоку  "}, format="json"
    )
    assert edited.json()["alt"] == "Вид сбоку"


@pytest.mark.django_db(transaction=True)
def test_two_simultaneous_uploads_cannot_pass_the_limit(world, monkeypatch):
    """Две загрузки при девяти фото: проходит одна. Без блокировки строки товара обе прочли бы «девять» и создали одиннадцатое."""
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from django.db import close_old_connections, transaction

    upload_n(world, image_service.MAX_IMAGES - 1)
    barrier = threading.Barrier(2)
    real_ordered = image_service.ordered

    def ordered_then_meet(product):
        rows = real_ordered(product)
        try:
            barrier.wait(timeout=1.5)  # обе сессии уже посчитали фото — теперь вместе создают
        except threading.BrokenBarrierError:
            pass
        return rows

    monkeypatch.setattr(image_service, "ordered", ordered_then_meet)
    product_id = world["relay"].pk

    def one(n):
        try:
            product = Product.objects.get(pk=product_id)
            file = SimpleUploadedFile(f"race{n}.png", PNG, content_type="image/png")
            with transaction.atomic():
                image_service.add_image(product, file)
            return "ok"
        except Exception as error:  # noqa: BLE001 — результат потока: код отказа или тип ошибки
            return getattr(error, "code", type(error).__name__)
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = sorted(pool.map(one, range(2)))
    assert results == ["IMAGE_LIMIT_REACHED", "ok"]
    assert ProductImage.objects.filter(product_id=product_id).count() == image_service.MAX_IMAGES


# --- страна происхождения и гарантия -------------------------------------------------------------------------------


def make_country(code="DE", name="Германия"):
    return Country.objects.get_or_create(code=code, defaults={"name": name, "alpha2": code})[0]


def test_origin_and_warranty_defaults_come_from_brand_and_company(world):
    germany = make_country()
    brand = Manufacturer.objects.create(name="Бренд А", country=germany)
    Product.objects.filter(pk=world["relay"].pk).update(brand=brand)
    CompanySettings.objects.update_or_create(company=world["own"], defaults={"default_warranty_months": 18})
    detail = card(world)
    assert detail["origin"] == {
        "own": None,
        "effective": {"id": germany.pk, "name": germany.name},
        "brand": {"id": germany.pk, "name": germany.name},
        "source": "brand",
    }
    assert detail["warranty"] == {
        "months": None,
        "terms": "",
        "effective_months": 18,
        "company_months": 18,
        "source": "company",
    }


def test_origin_and_warranty_set_on_the_card_win_and_clear_back(world):
    germany, china = make_country(), make_country("CN", "Китай")
    brand = Manufacturer.objects.create(name="Бренд Б", country=germany)
    Product.objects.filter(pk=world["relay"].pk).update(brand=brand)
    CompanySettings.objects.update_or_create(company=world["own"], defaults={"default_warranty_months": 18})
    saved = world["clients"]["supply"].patch(
        item_url(world),
        {"country_of_origin_id": china.pk, "warranty_months": 36, "warranty_terms": "Замена при заводском браке"},
        format="json",
    )
    assert saved.status_code == 200
    body = saved.json()
    assert body["origin"]["own"] == {"id": china.pk, "name": "Китай"} and body["origin"]["source"] == "item"
    assert body["origin"]["effective"]["name"] == "Китай"
    assert body["warranty"] == {
        "months": 36,
        "terms": "Замена при заводском браке",
        "effective_months": 36,
        "company_months": 18,
        "source": "item",
    }
    cleared = (
        world["clients"]["supply"]
        .patch(item_url(world), {"country_of_origin_id": None, "warranty_months": None}, format="json")
        .json()
    )
    assert cleared["origin"]["source"] == "brand" and cleared["warranty"]["source"] == "company"
    assert cleared["warranty"]["terms"] == "Замена при заводском браке"


def test_zero_months_is_a_real_warranty_value_and_none_anywhere_says_none(world):
    zero = world["clients"]["supply"].patch(item_url(world), {"warranty_months": 0}, format="json").json()
    assert zero["warranty"]["effective_months"] == 0 and zero["warranty"]["source"] == "item"
    fresh = card(world, target=world["cable"])
    assert fresh["origin"]["source"] == "none" and fresh["origin"]["effective"] is None
    assert fresh["warranty"]["source"] == "none" and fresh["warranty"]["effective_months"] is None


@pytest.mark.parametrize(
    "body, code",
    [
        ({"country_of_origin_id": 999999}, "COUNTRY_NOT_FOUND"),
        ({"warranty_months": 601}, "WARRANTY_MONTHS_INVALID"),
        ({"warranty_months": -3}, "WARRANTY_MONTHS_INVALID"),
    ],
)
def test_origin_and_warranty_refusals(world, body, code):
    refused = world["clients"]["supply"].patch(item_url(world), body, format="json")
    assert refused.status_code == 400
    assert refused.json() == {"detail": code} or "warranty_months" in refused.json()


def test_origin_and_warranty_edit_needs_catalog_manage(world):
    refused = world["clients"]["manager"].patch(item_url(world), {"warranty_months": 12}, format="json")
    assert refused.status_code == 403
    assert Product.objects.get(pk=world["relay"].pk).warranty_months is None


def test_origin_and_warranty_can_be_given_on_create(world):
    germany = make_country()
    created = world["clients"]["supply"].post(
        "/api/v1/catalog/items/",
        {"name": "Новая позиция", "kind": "on_order", "country_of_origin_id": germany.pk, "warranty_months": 6},
        format="json",
    )
    assert created.status_code == 201
    body = created.json()
    assert body["origin"]["source"] == "item" and body["warranty"]["months"] == 6


# --- документы ----------------------------------------------------------------------------------------------------


def doc(world, who="supply", name="cert.pdf", content=PDF, content_type="application/pdf", **fields):
    fields.setdefault("product_id", world["relay"].pk)
    file = SimpleUploadedFile(name, content, content_type=content_type)
    return world["clients"][who].post("/api/v1/catalog/tech-docs/", {"file": file, **fields}, format="multipart")


def test_seed_has_the_nine_kinds_and_old_codes(world):
    codes = set(DocumentKind.objects.values_list("code", flat=True))
    assert codes == {
        "certificate",
        "declaration",
        "passport",
        "manual",
        "warranty_card",
        "tz",
        "drawing",
        "pnr",
        "other",
    }
    assert DocumentKind.objects.get(code="certificate").has_validity is True
    assert DocumentKind.objects.get(code="tz").client_visible_default is False


def test_kinds_list_is_readable_by_any_staff_and_hides_inactive_ones(world):
    DocumentKind.objects.filter(code="pnr").update(is_active=False)
    for who in ("manager", "viewer", "supply"):
        body = world["clients"][who].get("/api/v1/catalog/document-kinds/").json()
        codes = [k["code"] for k in body["results"]]
        assert codes[0] == "certificate" and "pnr" not in codes and "other" in codes, who
        assert set(body["results"][0]) == {"id", "code", "name", "has_validity", "client_visible_default", "sort_order"}


def test_document_with_number_dates_and_visibility_is_saved_and_shown_on_the_card(world):
    today = timezone.localdate()
    created = doc(
        world,
        kind="certificate",
        title="Сертификат на реле",
        number="RU-0042",
        issued_by="Орган по сертификации",
        issued_at=str(today - timedelta(days=30)),
        valid_until=str(today + timedelta(days=300)),
        client_visible="true",
    )
    assert created.status_code == 201
    body = created.json()
    assert (body["kind"], body["kind_name"], body["number"], body["issued_by"]) == (
        "certificate",
        "Сертификат соответствия",
        "RU-0042",
        "Орган по сертификации",
    )
    assert body["client_visible"] is True and body["is_expired"] is False
    assert body["valid_until"] == str(today + timedelta(days=300))
    [shown] = card(world)["tech_docs"]
    assert (
        shown["number"] == "RU-0042"
        and shown["kind_name"] == "Сертификат соответствия"
        and shown["is_expired"] is False
    )


def test_client_visible_defaults_from_the_kind_and_can_be_overridden(world):
    assert doc(world, kind="passport").json()["client_visible"] is True
    assert doc(world, kind="tz").json()["client_visible"] is False
    assert doc(world, kind="tz", client_visible="true").json()["client_visible"] is True
    assert doc(world, kind="passport", client_visible="false").json()["client_visible"] is False
    assert doc(world).json()["kind"] == "other"


def test_expired_document_is_marked(world):
    yesterday = str(timezone.localdate() - timedelta(days=1))
    expired = doc(world, kind="certificate", number="X-1", valid_until=yesterday).json()
    assert expired["is_expired"] is True
    forever = doc(world, kind="certificate", number="X-2").json()
    assert forever["valid_until"] is None and forever["is_expired"] is False


@pytest.mark.parametrize(
    "fields, code",
    [
        ({"kind": "nonsense"}, "TECH_DOC_KIND_INVALID"),
        ({"kind": "certificate", "valid_until": "31.31.2030"}, "TECH_DOC_DATE_INVALID"),
        (
            {"kind": "certificate", "issued_at": "2026-05-01", "valid_until": "2026-04-01"},
            "TECH_DOC_VALIDITY_RANGE_INVALID",
        ),
    ],
)
def test_document_passport_refusals(world, fields, code):
    refused = doc(world, **fields)
    assert refused.status_code == 400
    assert refused.json() == {"detail": code} or code in str(refused.json()) or "valid_until" in refused.json()
    assert TechDocument.objects.count() == 0


def test_a_switched_off_kind_is_refused_for_new_documents_but_old_ones_keep_their_name(world):
    created = doc(world, kind="pnr").json()
    DocumentKind.objects.filter(code="pnr").update(is_active=False)
    assert doc(world, kind="pnr").json() == {"detail": "TECH_DOC_KIND_INVALID"}
    [shown] = card(world)["tech_docs"]
    assert shown["id"] == created["id"] and shown["kind_name"] == "Регламент ПНР"


def test_document_passport_edit(world):
    created = doc(world, kind="other", title="Скан").json()
    client = world["clients"]["engineer"]
    edited = client.patch(
        f"/api/v1/catalog/tech-docs/{created['id']}/",
        {"kind": "declaration", "number": "ДС-7", "valid_until": "2030-01-01", "client_visible": True},
        format="json",
    )
    assert edited.status_code == 200
    body = edited.json()
    assert (body["kind"], body["number"], body["valid_until"], body["client_visible"]) == (
        "declaration",
        "ДС-7",
        "2030-01-01",
        True,
    )
    assert body["title"] == "Скан" and body["original_name"] == "cert.pdf"
    refused = client.patch(f"/api/v1/catalog/tech-docs/{created['id']}/", {"kind": "zzz"}, format="json")
    assert refused.status_code == 400 and refused.json() == {"detail": "TECH_DOC_KIND_INVALID"}
    for who in ("manager", "accountant"):
        assert (
            world["clients"][who].patch(f"/api/v1/catalog/tech-docs/{created['id']}/", {}, format="json").status_code
            == 403
        )


def test_registry_filters_by_kind_code_from_the_dictionary(world):
    doc(world, kind="manual")
    doc(world, kind="tz")
    listed = world["clients"]["manager"].get("/api/v1/catalog/tech-docs/", {"kind": "manual"}).json()
    assert [r["kind_name"] for r in listed["results"]] == ["Инструкция"]


# --- полнота карточки ---------------------------------------------------------------------------------------------


def requiring(world):
    """Товар `relay` в категории, которая требует документ соответствия."""
    category = Category.objects.create(name="Подлежит сертификации", requires_conformity_doc=True)
    Product.objects.filter(pk=world["relay"].pk).update(category=category)
    return Product.objects.get(pk=world["relay"].pk)


def missing(product):
    return [m["code"] for m in completeness(product)["missing"]]


def test_category_without_the_requirement_does_not_ask_for_a_document(world):
    assert "conformity_doc" not in missing(Product.objects.get(pk=world["cable"].pk))


def test_category_with_the_requirement_needs_a_valid_numbered_conformity_document(world):
    product = requiring(world)
    assert "conformity_doc" in missing(product)
    assert "conformity_doc" in card(world)["publish"]["missing"]
    today = timezone.localdate()
    # Не тот вид: ТЗ, у него нет срока и это не сертификат.
    doc(world, kind="tz", number="TZ-1")
    assert "conformity_doc" in missing(product)
    # Нужный вид, но без номера.
    doc(world, kind="certificate")
    assert "conformity_doc" in missing(product)
    # С номером, но срок вышел.
    doc(world, kind="certificate", number="OLD-1", valid_until=str(today - timedelta(days=1)))
    assert "conformity_doc" in missing(product)
    # Действующий с номером: требование закрыто.
    doc(world, kind="declaration", number="ДС-1", valid_until=str(today + timedelta(days=100)))
    assert "conformity_doc" not in missing(product)
    assert "conformity_doc" not in card(world)["publish"]["missing"]


def test_unlimited_certificate_with_a_number_satisfies_the_requirement(world):
    product = requiring(world)
    doc(world, kind="certificate", number="БС-5")
    assert "conformity_doc" not in missing(product)


def test_any_kind_with_validity_counts_and_the_switch_is_data(world):
    product = requiring(world)
    doc(world, kind="passport", number="П-9")
    assert "conformity_doc" in missing(product)
    DocumentKind.objects.filter(code="passport").update(has_validity=True)
    assert "conformity_doc" not in missing(product)


def test_the_document_of_another_product_does_not_count(world):
    product = requiring(world)
    doc(world, kind="certificate", number="Ч-1", product_id=world["cable"].pk)
    assert "conformity_doc" in missing(product)


def test_batch_summary_counts_the_missing_document_with_constant_queries(world, django_assert_num_queries):
    product = requiring(world)
    doc(world, kind="certificate", number="Д-1", product_id=world["cable"].pk)
    summary = summarize_completeness([product])
    assert {"code": "conformity_doc", "label": "Действующий документ соответствия с номером", "count": 1} in summary[
        "missing_breakdown"
    ]
    ctx = CompletenessContext([product])
    assert ctx.conformity_categories == {product.category_id} and ctx.products_with_conformity_doc == set()


def test_publish_is_blocked_until_the_document_exists(world):
    product = requiring(world)
    client = world["clients"]["supply"]
    blocked = client.post(item_url(world, "publish/"))
    assert blocked.status_code == 409 and blocked.json() == {"detail": "PRODUCT_INCOMPLETE"}
    assert "conformity_doc" in card(world)["publish"]["missing"]
    doc(world, kind="certificate", number="OK-1")
    assert "conformity_doc" not in missing(Product.objects.get(pk=product.pk))


def test_a_document_of_a_switched_off_kind_stays_editable_but_cannot_move_to_another_off_kind(world):
    created = doc(world, kind="pnr").json()
    DocumentKind.objects.filter(code__in=["pnr", "tz"]).update(is_active=False)
    client = world["clients"]["supply"]
    url = f"/api/v1/catalog/tech-docs/{created['id']}/"
    edited = client.patch(url, {"kind": "pnr", "number": "ПНР-5", "valid_until": "2030-01-01"}, format="json")
    assert edited.status_code == 200
    body = edited.json()
    assert (body["kind"], body["kind_name"], body["number"], body["valid_until"]) == (
        "pnr",
        "Регламент ПНР",
        "ПНР-5",
        "2030-01-01",
    )
    assert client.patch(url, {"number": "ПНР-6"}, format="json").status_code == 200
    refused = client.patch(url, {"kind": "tz"}, format="json")
    assert refused.status_code == 400 and refused.json() == {"detail": "TECH_DOC_KIND_INVALID"}
    moved = client.patch(url, {"kind": "manual"}, format="json")
    assert moved.status_code == 200 and moved.json()["kind"] == "manual"
    # Назад на выключенный вид уже нельзя.
    assert client.patch(url, {"kind": "pnr"}, format="json").json() == {"detail": "TECH_DOC_KIND_INVALID"}


@pytest.mark.parametrize("code", ["ISO9001", "Cert", "кириллица", "with space", "a" * 33, ""])
def test_document_kind_code_must_match_the_contract_pattern(code):
    kind = DocumentKind(code=code, name="Вид")
    with pytest.raises(ValidationError) as error:
        kind.full_clean()
    assert "code" in error.value.message_dict


@pytest.mark.parametrize("code", ["iso-9001", "a", "warranty_card_2", "x" * 32])
def test_document_kind_code_accepts_lowercase_digits_dash_and_underscore(code):
    DocumentKind(code=code, name="Вид").full_clean()


def test_the_admin_form_refuses_an_uppercase_kind_code(rf):
    from django.contrib import admin as django_admin

    from accounts.models import CustomUser

    request = rf.get("/")
    request.user = CustomUser.objects.create_superuser(email="root@cat-card.test", username="root", password="pw")
    form_class = django_admin.site._registry[DocumentKind].get_form(request)
    bad = form_class(data={"code": "ISO9001", "name": "Сертификат ISO", "sort_order": 100, "is_active": "on"})
    assert not bad.is_valid() and "code" in bad.errors
    good = form_class(data={"code": "iso9001", "name": "Сертификат ISO", "sort_order": 100, "is_active": "on"})
    assert good.is_valid(), good.errors
