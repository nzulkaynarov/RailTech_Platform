"""ЕД-4: позиция в строке любого документа — `{id, name, sku, kind, photo}` и миниатюра главного фото для любого сотрудника.

Мир — `desk_world`. Фото — настоящая картинка (Pillow), иначе миниатюру не построить.
"""

from io import BytesIO

import pytest
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from catalog.desk import images
from catalog.item_ref import item_ref, main_photos
from catalog.tests.desk_world import build_world

pytestmark = pytest.mark.django_db


@pytest.fixture
def world():
    cache.clear()
    return build_world()


def _png(width=300, height=200, color=(200, 30, 30)) -> bytes:
    out = BytesIO()
    Image.new("RGB", (width, height), color).save(out, format="PNG")
    return out.getvalue()


def _photo(world, product, *, main=False, color=(200, 30, 30)):
    file = SimpleUploadedFile("p.png", _png(color=color), content_type="image/png")
    response = world["clients"]["supply"].post(
        f"/api/v1/catalog/items/{product.pk}/images/", {"image": file, "is_main": main}, format="multipart"
    )
    assert response.status_code == 201, response.json()
    return response.json()["id"]


def test_ref_names_the_card_and_its_type(world):
    relay, service = world["relay"], world["commissioning"]
    assert item_ref(relay) == {"id": relay.pk, "name": relay.name, "sku": relay.sku, "kind": "goods", "photo": None}
    assert item_ref(service)["kind"] == "service"
    assert item_ref(None) is None


def test_photo_is_the_main_one_and_follows_a_new_main(world):
    relay = world["relay"]
    first = _photo(world, relay)
    _photo(world, relay, color=(0, 0, 200))
    assert item_ref(relay)["photo"] == first, "главное — первое загруженное"
    newer = _photo(world, relay, main=True, color=(0, 200, 0))
    assert main_photos([relay.pk, world["cable"].pk, None]) == {relay.pk: newer}, "id меняется — клиент сбросит кэш"


@pytest.mark.parametrize("who", ["manager", "accountant", "viewer"])
def test_any_staff_reads_a_square_webp_thumbnail(world, who):
    relay = world["relay"]
    _photo(world, relay)

    response = world["clients"][who].get(f"/api/v1/catalog/items/{relay.pk}/thumbnail/")

    assert response.status_code == 200
    assert response["Content-Type"] == "image/webp"
    with Image.open(BytesIO(response.content)) as thumb:
        assert thumb.format == "WEBP"
        assert thumb.size == (images.THUMBNAIL_SIDE, images.THUMBNAIL_SIDE)


def test_no_photo_is_404_and_the_client_shows_the_type_icon(world):
    response = world["clients"]["manager"].get(f"/api/v1/catalog/items/{world['cable'].pk}/thumbnail/")
    assert response.status_code == 404


def test_catalog_rows_carry_the_photo(world):
    relay = world["relay"]
    image_id = _photo(world, relay)
    rows = world["clients"]["manager"].get("/api/v1/catalog/items/", {"q": "Реле"}).json()["results"]
    assert [(row["id"], row["photo"]) for row in rows] == [(relay.pk, image_id)]


def test_quote_line_carries_the_ref_with_one_photo_lookup_per_quote(world):
    from rest_framework.test import APIRequestFactory

    from crm.models import Deal, DealStage, Quote, QuoteItem
    from crm.serializers import QuoteItemSerializer

    relay, cable = world["relay"], world["cable"]
    image_id = _photo(world, relay)
    stage = DealStage.objects.get_or_create(code="DRAFT", defaults={"name": "Draft", "sort_order": 10})[0]
    deal = Deal.objects.create(title="d", company=world["own"], stage=stage)
    quote = Quote.objects.create(deal=deal, version=1)
    # bulk_create — мимо движка расчёта в save(): сериализатору нужны только строка и карточка
    lines = QuoteItem.objects.bulk_create(
        [QuoteItem(quote=quote, product=relay, position=1, quantity=1), QuoteItem(quote=quote, position=2, quantity=1)]
    )
    lines.append(QuoteItem.objects.bulk_create([QuoteItem(quote=quote, product=cable, position=3, quantity=1)])[0])
    request = APIRequestFactory().get("/")
    request.user = world["users"]["manager"]
    context = {"request": request}
    rows = [QuoteItemSerializer(QuoteItem.objects.get(pk=line.pk), context=context).data for line in lines]

    assert [row["item"] and (row["item"]["id"], row["item"]["photo"]) for row in rows] == [
        (relay.pk, image_id),
        None,
        (cable.pk, None),
    ]
    assert list(context["item_photos"]) == [quote.pk], "фото строк КП — одной выборкой на КП"
