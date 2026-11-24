"""ЕД-4 в Cabinet: позиция строки КП — `item` с фото, миниатюра — по правилу видимости портала.

Клиент видит фото позиции своего КП и опубликованной позиции витрины; чужой компании и неопубликованной позиции вне его КП
— 404, как и позиции без фото. Партнёр видит фото своей карточки; у сопоставленной чужой черновой — нет ни `photo`, ни
миниатюры.
"""

from __future__ import annotations

from io import BytesIO

import pytest
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image
from portal.tests.contract_world import make_quote
from portal.tests.partner_world import partner_world  # noqa: F401

from catalog.desk import images
from catalog.models import Product, ProductStatus
from crm.constants import QuoteStatusCode
from crm.models import QuoteItem

pytestmark = pytest.mark.django_db

API = "/api/portal/v1"


@pytest.fixture(autouse=True)
def _fresh_cache():
    cache.clear()


def _photo(product) -> int:
    out = BytesIO()
    Image.new("RGB", (240, 160), (30, 120, 200)).save(out, format="PNG")
    return images.add_image(product, SimpleUploadedFile("p.png", out.getvalue(), content_type="image/png")).pk


def _thumb(client, product):
    return client.get(f"{API}/items/{product.pk}/thumbnail", {"v": "1"})


def test_quote_line_carries_the_item_and_the_client_reads_its_thumbnail(contract_world, portal_client):
    product = contract_world["product"]
    image_id = _photo(product)
    quote = make_quote(contract_world["main"], 30, QuoteStatusCode.SENT, uzs=contract_world["uzs"], items=False)
    QuoteItem.objects.create(quote=quote, product=product, imported_raw_name="труба клиента", quantity=3, unit="")

    response = portal_client.get(f"{API}/quotes/{quote.pk}")

    assert response.status_code == 200
    assert response.json()["lines"][0]["item"] == {
        "id": product.pk,
        "name": product.name,
        "sku": product.sku,
        "kind": "goods",
        "photo": image_id,
    }
    thumb = _thumb(portal_client, product)
    assert thumb.status_code == 200 and thumb["Content-Type"] == "image/webp"


def test_unpublished_item_of_the_clients_quote_is_visible_only_to_that_client(
    contract_world, portal_client, other_portal_client
):
    draft = Product.objects.create(
        name="Деталь по чертежу", status=ProductStatus.objects.get_or_create(code="DRAFT", defaults={"name": "Ч"})[0]
    )
    _photo(draft)
    assert _thumb(portal_client, draft).status_code == 404, "вне КП клиента черновую позицию не показываем"

    quote = make_quote(contract_world["main"], 31, QuoteStatusCode.SENT, uzs=contract_world["uzs"], items=False)
    QuoteItem.objects.create(quote=quote, product=draft, imported_raw_name="деталь", quantity=1, unit="")

    assert _thumb(portal_client, draft).status_code == 200
    assert _thumb(other_portal_client, draft).status_code == 404, "чужая компания"


def test_no_photo_is_the_same_404(contract_world, portal_client):
    assert _thumb(portal_client, contract_world["product"]).status_code == 404


def test_partner_sees_own_photo_but_not_a_matched_foreign_draft(partner_world):  # noqa: F811
    world = partner_world
    own, foreign = world["cards"]["draft"], world["cards"]["b_draft_with_a_offer"]
    own_photo = _photo(own)
    _photo(foreign)

    items = {row["id"]: row for row in world["client_a"].get(f"{API}/partner/products").json()["items"]}

    assert items[own.pk]["photo"] == own_photo
    assert items[foreign.pk]["photo"] is None
    assert _thumb(world["client_a"], own).status_code == 200
    assert _thumb(world["client_a"], foreign).status_code == 404
    assert _thumb(world["client_b"], own).status_code == 404, "черновик А партнёру Б не виден"


def test_catalog_list_and_card_carry_the_item_and_its_thumbnail_is_readable(contract_world, portal_client):
    product = contract_world["product"]
    image_id = _photo(product)
    expected = {"id": product.pk, "name": product.name, "sku": product.sku, "kind": "goods", "photo": image_id}

    listed = portal_client.get(f"{API}/catalog").json()["items"]
    card = portal_client.get(f"{API}/catalog/{product.pk}").json()

    assert {row["id"]: row["item"] for row in listed}[product.pk] == expected
    assert card["item"] == expected
    assert _thumb(portal_client, product).status_code == 200, "витрина видит миниатюру опубликованной позиции"
    assert set(card["item"]) == {"id", "name", "sku", "kind", "photo"}, "в строке только id фото, адреса хранилища нет"
